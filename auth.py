import os
import re
import hmac
import secrets
import datetime
from flask import Blueprint, request, jsonify, session, url_for, redirect, current_app, g
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
        "INSERT INTO users (email, password_hash, auth_provider, email_verified, display_name, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
        (email, password_hash, "password", display_name, now, now)
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
    
    # Send verification email
    verify_url = url_for("gui_index", _external=True) + f"?verify_token={raw_token}"
    email_body = f"Hello,\n\nPlease verify your email by clicking this link:\n{verify_url}\n\nThis link will expire in 24 hours."
    typemeter_db.send_email(email, "Verify your TypeMeter Account", email_body)
    
    return jsonify({"message": "Registration successful. Please check your email to verify your account."}), 201

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
        
    db = g.db
    
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
        # Increment failed attempts
        failed = user["failed_login_attempts"] + 1
        lockout_until = None
        if failed >= 5:
            lockout_until = (now + datetime.timedelta(minutes=15)).isoformat()
            
        db.execute(
            "UPDATE users SET failed_login_attempts = ?, lockout_until = ?, updated_at = ? WHERE id = ?",
            (failed, lockout_until, now.isoformat(), user["id"])
        )
        db.commit()
        
        if failed >= 5:
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
    
    return jsonify({
        "message": "Login successful.",
        "user": {
            "email": user["email"],
            "display_name": user["display_name"],
            "email_verified": bool(user["email_verified"])
        }
    })

@auth_bp.route("/logout", methods=["POST"])
def logout():
    db = g.db
    session_id = session.get("session_id")
    if session_id:
        typemeter_db.delete_session(db, session_id)
        session.pop("session_id", None)
    return jsonify({"message": "Logout successful."})

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
            db.execute("UPDATE users SET email_verified = 1, updated_at = ? WHERE id = ?", (now.isoformat(), row["user_id"]))
            db.execute("UPDATE email_verification_tokens SET used_at = ? WHERE token_hash = ?", (now.isoformat(), token_hash))
    except Exception as e:
        return redirect(url_for("gui_index") + f"?verify_error=An error occurred: {e}")
        
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
        # Prevent user enumeration (always return success message)
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
    
    # Send verification email
    verify_url = url_for("gui_index", _external=True) + f"?verify_token={raw_token}"
    email_body = f"Hello,\n\nPlease verify your email by clicking this link:\n{verify_url}\n\nThis link will expire in 24 hours."
    typemeter_db.send_email(email, "Verify your TypeMeter Account", email_body)
    
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
        # Safe against user enumeration: always return success message
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
    
    # Send email
    reset_url = url_for("gui_index", _external=True) + f"?reset_token={raw_token}"
    email_body = f"Hello,\n\nYou requested a password reset. Reset your password by clicking this link:\n{reset_url}\n\nThis link will expire in 1 hour."
    typemeter_db.send_email(email, "Reset your TypeMeter Password", email_body)
    
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
        return jsonify({"error": f"An error occurred: {e}"}), 500
        
    return jsonify({"message": "Password updated successfully. Please log in with your new password."})

@auth_bp.route("/google", methods=["GET"])
def google_login():
    """Redirects the client to Google's OAuth consent screen."""
    # Ensure OAuth is registered
    if "google" not in oauth._clients:
        return jsonify({"error": "Google Sign-In is not configured on this server."}), 501
        
    redirect_uri = url_for("auth.google_callback", _external=True)
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
        return redirect(url_for("gui_index") + f"?auth_error=OAuth handshake failed: {e}")
        
    userinfo = token.get("userinfo")
    if not userinfo:
        return redirect(url_for("gui_index") + "?auth_error=Failed to retrieve profile data from Google ID token.")
        
    # Extract profile attributes
    google_id = userinfo.get("sub")
    email = userinfo.get("email", "").strip().lower()
    name = userinfo.get("name")
    
    if not google_id or not email:
        return redirect(url_for("gui_index") + "?auth_error=Google profile payload incomplete.")
        
    db = g.db
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # 1. Lookup user by google_id
    user = db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
    if not user:
        # 2. Lookup existing user by email
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user:
            # 3. Account Linking: Add google_id and display name if missing, keeping auth_provider details
            db.execute(
                "UPDATE users SET google_id = ?, display_name = COALESCE(display_name, ?), email_verified = 1, updated_at = ? WHERE id = ?",
                (google_id, name, now, user["id"])
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        else:
            # 4. Create new Google OAuth account
            cursor = db.cursor()
            cursor.execute(
                "INSERT INTO users (email, password_hash, auth_provider, google_id, email_verified, display_name, created_at, updated_at) VALUES (?, NULL, ?, ?, 1, ?, ?, ?)",
                (email, "google", google_id, name, now, now)
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
            
    # Create session with fixation protection
    session_id = typemeter_db.create_session(db, user["id"])
    session["session_id"] = session_id
    
    return redirect(url_for("gui_index") + "?auth_success=Login successful via Google!")

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
    
    user = db.execute("SELECT email, display_name, email_verified FROM users WHERE id = ?", (session_row["user_id"],)).fetchone()
    if not user:
        return jsonify({"authenticated": False})
        
    return jsonify({
        "authenticated": True,
        "user": {
            "email": user["email"],
            "display_name": user["display_name"],
            "email_verified": bool(user["email_verified"])
        }
    })
