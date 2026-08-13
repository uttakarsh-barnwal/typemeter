import os
import re
import hmac
import secrets
import datetime
from flask import Blueprint, request, jsonify, session, url_for, redirect, current_app, g, make_response
from authlib.integrations.flask_client import OAuth
import typemeter_db

auth_bp = Blueprint("auth", __name__)
oauth = OAuth()

def init_oauth(app):
    """Initializes Authlib Google client using environment configurations."""
    oauth.init_app(app)
    google_id = os.environ.get("GOOGLE_CLIENT_ID")
    google_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    
    # If Google OAuth parameters are defined, register the client
    if google_id and google_secret:
        oauth.register(
            name="google",
            client_id=google_id,
            client_secret=google_secret,
            server_metadata_url=os.environ.get("GOOGLE_DISCOVERY_URL", "https://accounts.google.com/.well-known/openid-configuration"),
            client_kwargs={
                "scope": "openid email profile"
            }
        )

# --- Password Policy Validator ---
def validate_password_policy(password):
    """Enforces: length >= 8, must contain at least one letter and one number."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r"[A-Za-z]", password):
        return False, "Password must contain at least one letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number."
    return True, ""

# --- Authentication Endpoints ---

@auth_bp.route("/signup", methods=["POST"])
def signup():
    # Persistent IP-based signup rate limit (max 10 accounts per IP per hour)
    db = g.db
    ip = request.remote_addr or "unknown_ip"
    if not typemeter_db.check_rate_limit(db, ip, "signup", 10, 3600):
        return jsonify({"error": "Too many signups from this IP address. Please try again later."}), 429
        
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    display_name = data.get("display_name", "").strip() or None
    
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
        
    # Email format validation
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"error": "Invalid email address format."}), 400
        
    # Password complexity validation
    valid_pwd, pwd_err = validate_password_policy(password)
    if not valid_pwd:
        return jsonify({"error": pwd_err}), 400
        
    # Check uniqueness
    row = db.execute("SELECT id, auth_provider FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        if row["auth_provider"] == "google":
            return jsonify({"error": "This email is registered via Google sign-in. Please use Sign in with Google."}), 400
        else:
            return jsonify({"error": "Email address already registered."}), 400
            
    # Hash password & save user
    password_hash = typemeter_db.hash_password(password)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO users (email, password_hash, auth_provider, email_verified, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (email, password_hash, "password", False, display_name, now, now)
    )
    user_id = cursor.lastrowid
    
    # Generate verification token
    raw_token = secrets.token_urlsafe(32)
    token_hash = typemeter_db.hash_token(raw_token)
    expires_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)).isoformat()
    
    cursor.execute(
        "INSERT INTO email_verification_tokens (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (user_id, token_hash, expires_at, now)
    )
    db.commit()
    
    # Send verification email asynchronously
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        verify_url = f"{base_url}/?verify_token={raw_token}"
    else:
        verify_url = url_for("gui_index", _external=True) + f"?verify_token={raw_token}"
    email_body = f"Hello,\n\nPlease verify your email by clicking this link:\n{verify_url}\n\nThis link will expire in 24 hours."
    typemeter_db.send_email_async(email, "Verify your TypeMeter Account", email_body)
    
    # Create session with fixation protection & migrate anonymous history if present
    # Create session with fixation protection & migrate anonymous history on account creation only
    session_id = typemeter_db.create_session(db, user_id)
    session["session_id"] = session_id
    
    anon_cookie = request.cookies.get("identity_id")
    if anon_cookie:
        typemeter_db.migrate_anonymous_data(db, anon_cookie, user_id)
    
    response = make_response(jsonify({
        "message": "Registration successful. Please check your email to verify your account.",
        "user": {
            "id": user_id,
            "email": email,
            "display_name": display_name,
            "email_verified": False
        }
    }), 201)
    response.delete_cookie("identity_id", path="/")
    return response

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
        
    db = g.db
    ip = request.remote_addr or "unknown_ip"
    if not typemeter_db.check_rate_limit(db, f"login_{ip}", "login", 15, 600):
        return jsonify({"error": "Too many login attempts from this IP. Please try again in 10 minutes."}), 429
        
    # User lockout / rate limit check
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    now = datetime.datetime.now(datetime.timezone.utc)
    
    if user and user["lockout_until"]:
        lockout_time = datetime.datetime.fromisoformat(user["lockout_until"])
        if now.timestamp() < lockout_time.timestamp():
            return jsonify({"error": "Account is temporarily locked due to too many failed login attempts. Please try again later."}), 429
            
    # Verification and authentication
    if not user or user["auth_provider"] != "password" or not user["password_hash"]:
        # Constant-time dummy check to prevent timing analysis on username existence
        typemeter_db.verify_password("dummy_password", "$2b$12$DummyPasswordHashPlaceholderThatTakesTimeToCompare")
        return jsonify({"error": "Invalid email or password."}), 401
        
    if not typemeter_db.verify_password(password, user["password_hash"]):
        # Atomic increment of failed_login_attempts and conditional lockout calculation
        lockout_time_str = (now + datetime.timedelta(minutes=15)).isoformat()
        db.execute(
            """
            UPDATE users 
            SET failed_login_attempts = failed_login_attempts + 1, 
                lockout_until = CASE WHEN failed_login_attempts + 1 >= 5 THEN ? ELSE lockout_until END, 
                updated_at = ? 
            WHERE id = ?
            """,
            (lockout_time_str, now.isoformat(), user["id"])
        )
        db.commit()
        
        updated_user = db.execute("SELECT failed_login_attempts FROM users WHERE id = ?", (user["id"],)).fetchone()
        current_failed = updated_user["failed_login_attempts"] if updated_user else 5
        
        if current_failed >= 5:
            return jsonify({"error": "Too many failed login attempts. Your account has been locked for 15 minutes."}), 429
        return jsonify({"error": "Invalid email or password."}), 401
        
    # Reset failed attempts on success
    db.execute(
        "UPDATE users SET failed_login_attempts = 0, lockout_until = NULL, updated_at = ? WHERE id = ?",
        (now.isoformat(), user["id"])
    )
    db.commit()
    
    # Create session with fixation protection (new session ID generated)
    session_id = typemeter_db.create_session(db, user["id"])
    session["session_id"] = session_id
    
    response = make_response(jsonify({
        "message": "Login successful.",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "email_verified": bool(user["email_verified"])
        }
    }))
    response.delete_cookie("identity_id", path="/")
    return response

@auth_bp.route("/logout", methods=["POST"])
def logout():
    db = g.db
    session_id = session.get("session_id")
    if session_id:
        typemeter_db.delete_session(db, session_id)
        session.pop("session_id", None)
    response = make_response(jsonify({"message": "Logout successful."}))
    response.delete_cookie("identity_id", path="/")
    return response

@auth_bp.route("/verify-email", methods=["GET"])
def verify_email():
    raw_token = request.args.get("token", "")
    if not raw_token:
        return redirect(url_for("gui_index") + "?verify_error=Missing verification token.")
        
    db = g.db
    token_hash = typemeter_db.hash_token(raw_token)
    
    # Atomic fetch and check using transaction isolation via connection context manager
    try:
        with db:
            row = db.execute("SELECT * FROM email_verification_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
            if not row or row["used_at"]:
                return redirect(url_for("gui_index") + "?verify_error=Token is invalid or has already been used.")
                
            now = datetime.datetime.now(datetime.timezone.utc)
            expires_at = datetime.datetime.fromisoformat(row["expires_at"])
            
            if now.timestamp() > expires_at.timestamp():
                return redirect(url_for("gui_index") + "?verify_error=Verification link has expired.")
                
            # Verify user
            db.execute("UPDATE users SET email_verified = ?, updated_at = ? WHERE id = ?", (True, now.isoformat(), row["user_id"]))
            db.execute("UPDATE email_verification_tokens SET used_at = ? WHERE token_hash = ?", (now.isoformat(), token_hash))
    except Exception as e:
        current_app.logger.error(f"Error during email verification: {e}", exc_info=True)
        return redirect(url_for("gui_index") + "?verify_error=An error occurred during verification. Please try again.")
        
    return redirect(url_for("gui_index") + "?verify_success=Your email has been verified successfully!")

@auth_bp.route("/resend-verification", methods=["POST"])
def resend_verification():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email address is required."}), 400
        
    db = g.db
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        # Perform dummy token hashing to balance timing between branches
        typemeter_db.hash_token("dummy_token_for_timing_mitigation")
        return jsonify({"message": "Verification link sent if the email exists."})
        
    # Check rate limit: max 1 request per 5 minutes per user account
    if not typemeter_db.check_rate_limit(db, f"resend_{user['id']}", "resend_verification", 1, 300):
        return jsonify({"error": "Please wait at least 5 minutes before requesting another verification link."}), 429
        
    # Invalidate previous verification tokens
    db.execute("UPDATE email_verification_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL", 
               (datetime.datetime.now(datetime.timezone.utc).isoformat(), user["id"]))
    
    # Generate new verification token
    raw_token = secrets.token_urlsafe(32)
    token_hash = typemeter_db.hash_token(raw_token)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = (now + datetime.timedelta(hours=24)).isoformat()
    
    db.execute(
        "INSERT INTO email_verification_tokens (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (user["id"], token_hash, expires_at, now.isoformat())
    )
    db.commit()
    
    # Send verification email asynchronously
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        verify_url = f"{base_url}/?verify_token={raw_token}"
    else:
        verify_url = url_for("gui_index", _external=True) + f"?verify_token={raw_token}"
    email_body = f"Hello,\n\nPlease verify your email by clicking this link:\n{verify_url}\n\nThis link will expire in 24 hours."
    typemeter_db.send_email_async(email, "Verify your TypeMeter Account", email_body)
    
    return jsonify({"message": "Verification link sent if the email exists."})

@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    # IP-based rate limiting to prevent email-bombing vectors (max 10 requests per IP per hour)
    db = g.db
    ip = request.remote_addr or "unknown_ip"
    if not typemeter_db.check_rate_limit(db, ip, "forgot_password_ip", 10, 3600):
        return jsonify({"error": "Too many password reset requests from this IP. Please try again later."}), 429
        
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email is required."}), 400
        
    # Rate limit requests per email address (max 3 per hour)
    if not typemeter_db.check_rate_limit(db, f"pwd_reset_{email}", "forgot_password_email", 3, 3600):
        return jsonify({"error": "Too many reset attempts for this email. Please try again later."}), 429
        
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or user["auth_provider"] != "password":
        # Perform dummy token hashing to balance timing between branches
        typemeter_db.hash_token("dummy_token_for_timing_mitigation")
        return jsonify({"message": "If the account exists, a password reset link has been sent."})
        
    # Invalidate older password reset tokens
    db.execute("UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
               (datetime.datetime.now(datetime.timezone.utc).isoformat(), user["id"]))
    
    # Generate reset token
    raw_token = secrets.token_urlsafe(32)
    token_hash = typemeter_db.hash_token(raw_token)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = (now + datetime.timedelta(hours=1)).isoformat() # 1 hour reset token lifespan
    
    db.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (user["id"], token_hash, expires_at, now.isoformat())
    )
    db.commit()
    
    # Send email asynchronously
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        reset_url = f"{base_url}/?reset_token={raw_token}"
    else:
        reset_url = url_for("gui_index", _external=True) + f"?reset_token={raw_token}"
    email_body = f"Hello,\n\nYou requested a password reset. Reset your password by clicking this link:\n{reset_url}\n\nThis link will expire in 1 hour."
    typemeter_db.send_email_async(email, "Reset your TypeMeter Password", email_body)
    
    return jsonify({"message": "If the account exists, a password reset link has been sent."})

@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json() or {}
    raw_token = data.get("token", "")
    new_password = data.get("new_password", "")
    
    if not raw_token or not new_password:
        return jsonify({"error": "Reset token and new password are required."}), 400
        
    valid_pwd, pwd_err = validate_password_policy(new_password)
    if not valid_pwd:
        return jsonify({"error": pwd_err}), 400
        
    db = g.db
    token_hash = typemeter_db.hash_token(raw_token)
    
    # Fetch and check token atomically
    try:
        with db:
            row = db.execute("SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
            if not row or row["used_at"]:
                return jsonify({"error": "Token is invalid or has already been used."}), 400
                
            now = datetime.datetime.now(datetime.timezone.utc)
            expires_at = datetime.datetime.fromisoformat(row["expires_at"])
            if now.timestamp() > expires_at.timestamp():
                return jsonify({"error": "Password reset token has expired."}), 400
                
            # Update user password & invalidate token
            password_hash = typemeter_db.hash_password(new_password)
            db.execute("UPDATE users SET password_hash = ?, failed_login_attempts = 0, lockout_until = NULL, updated_at = ? WHERE id = ?",
                       (password_hash, now.isoformat(), row["user_id"]))
            db.execute("UPDATE password_reset_tokens SET used_at = ? WHERE token_hash = ?", (now.isoformat(), token_hash))
            
            # Invalidate all active sessions for this user (security requirement)
            typemeter_db.invalidate_user_sessions(db, row["user_id"])
    except Exception as e:
        current_app.logger.error(f"Error during password reset: {e}", exc_info=True)
        return jsonify({"error": "An error occurred while resetting password. Please try again."}), 500
        
    return jsonify({"message": "Password updated successfully. Please log in with your new password."})

@auth_bp.route("/google", methods=["GET"])
def google_login():
    """Redirects the client to Google's OAuth consent screen."""
    # Ensure OAuth is registered
    if "google" not in oauth._clients:
        return jsonify({"error": "Google Sign-In is not configured on this server."}), 501
        
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        redirect_uri = f"{base_url}{url_for('auth.google_callback')}"
    else:
        redirect_uri = url_for("auth.google_callback", _external=True)

    current_app.logger.info(f"Google OAuth redirect_uri: {redirect_uri}")
    # Authlib automatically generates a random 'state' parameter, stores it in session,
    # and validates it during callback verification to prevent CSRF.
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route("/google/callback", methods=["GET"])
def google_callback():
    """Handles Google OAuth token exchange and authentication."""
    if "google" not in oauth._clients:
        return redirect(url_for("gui_index") + "?auth_error=Google Sign-In is not configured.")
        
    try:
        # Exchanges OAuth code for tokens, verifying signatures and audience claims
        token = oauth.google.authorize_access_token()
    except Exception as e:
        current_app.logger.error(f"Error during Google OAuth handshake: {e}", exc_info=True)
        return redirect(url_for("gui_index") + "?auth_error=OAuth handshake failed. Please try again.")
        
    userinfo = token.get("userinfo")
    if not userinfo:
        return redirect(url_for("gui_index") + "?auth_error=Failed to retrieve profile data from Google ID token.")
        
    # Extract profile attributes
    google_id = userinfo.get("sub")
    email = userinfo.get("email", "").strip().lower()
    name = userinfo.get("name")
    email_verified = userinfo.get("email_verified", False)
    
    if not google_id or not email:
        return redirect(url_for("gui_index") + "?auth_error=Google profile payload incomplete.")
        
    if not email_verified:
        return redirect(url_for("gui_index") + "?auth_error=Google account email is not verified by Google.")
        
    db = g.db
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # 1. Lookup user by google_id
    user = db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
    is_new_user = False
    if not user:
        # 2. Lookup existing user by email
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user:
            # 3. Account Linking: Add google_id and display name if missing, keeping auth_provider details
            db.execute(
                "UPDATE users SET google_id = ?, display_name = COALESCE(display_name, ?), email_verified = ?, updated_at = ? WHERE id = ?",
                (google_id, name, True, now, user["id"])
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        else:
            # 4. Create new Google OAuth account
            is_new_user = True
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO users (email, password_hash, auth_provider, google_id, email_verified, display_name, created_at, updated_at) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)",
                (email, "google", google_id, True, name, now, now)
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
            
    # Create session with fixation protection
    session_id = typemeter_db.create_session(db, user["id"])
    session["session_id"] = session_id
    
    if is_new_user:
        anon_cookie = request.cookies.get("identity_id")
        if anon_cookie:
            typemeter_db.migrate_anonymous_data(db, anon_cookie, user["id"])
    
    response = make_response(redirect(url_for("gui_index") + "?auth_success=Login successful via Google!"))
    response.delete_cookie("identity_id", path="/")
    return response

@auth_bp.route("/me", methods=["GET"])
def get_current_user():
    """Endpoint returning authenticated session state info."""
    db = g.db
    session_id = session.get("session_id")
    session_row = typemeter_db.get_session(db, session_id)
    
    if not session_row:
        return jsonify({"authenticated": False})
        
    # Touch session to update activity
    typemeter_db.touch_session(db, session_id)
    
    user = db.execute("SELECT id, email, display_name, email_verified, auth_provider, password_hash FROM users WHERE id = ?", (session_row["user_id"],)).fetchone()
    if not user:
        return jsonify({"authenticated": False})
        
    has_password = bool(user["password_hash"] and user["auth_provider"] == "password")
        
    return jsonify({
        "authenticated": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "email_verified": bool(user["email_verified"]),
            "auth_provider": user["auth_provider"],
            "has_password": has_password
        }
    })

@auth_bp.route("/change-password", methods=["POST"])
def change_password():
    """Authenticated endpoint allowing users to update their account password."""
    db = g.db
    session_id = session.get("session_id")
    session_row = typemeter_db.get_session(db, session_id)
    
    if not session_row:
        return jsonify({"error": "Authentication required."}), 401
        
    user_id = session_row["user_id"]
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return jsonify({"error": "User account not found."}), 404
        
    # Check if Google-only account without password
    if not user["password_hash"] or user["auth_provider"] != "password":
        return jsonify({"error": "Accounts registered via Google OAuth cannot change password."}), 400
        
    data = request.get_json() or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    
    if not current_password or not new_password:
        return jsonify({"error": "Current password and new password are required."}), 400
        
    # Verify current password
    if not typemeter_db.verify_password(current_password, user["password_hash"]):
        return jsonify({"error": "Incorrect current password."}), 401
        
    # Validate new password policy
    valid_pwd, pwd_err = validate_password_policy(new_password)
    if not valid_pwd:
        return jsonify({"error": pwd_err}), 400
        
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_hash = typemeter_db.hash_password(new_password)
    
    db.execute(
        "UPDATE users SET password_hash = ?, failed_login_attempts = 0, lockout_until = NULL, updated_at = ? WHERE id = ?",
        (new_hash, now, user_id)
    )
    db.commit()
    
    # Invalidate all other active sessions for this user while keeping the current session
    typemeter_db.invalidate_user_sessions(db, user_id, keep_session_id=session_id)
    
    return jsonify({"message": "Password updated successfully."})
