#!/usr/bin/env python3
import os
import re
import sys
import uuid
import hmac
import socket
import secrets
import datetime
import webbrowser
import threading
from urllib.parse import urlparse
from flask import Flask, request, jsonify, session, make_response, send_from_directory
from dotenv import load_dotenv
import typemeter_db

# Port configurations
START_PORT = 8000
MAX_PORT_ATTEMPTS = 100

def get_free_port(start_port):
    """Finds an available TCP port starting from start_port."""
    for port in range(start_port, start_port + MAX_PORT_ATTEMPTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('localhost', port))
                return port
            except socket.error:
                continue
    raise OSError("Could not find an open port.")

def init_dotenv():
    """Initializes .env file from .env.example if missing, generating a secure SECRET_KEY."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, ".env")
    env_example_path = os.path.join(script_dir, ".env.example")
    
    if not os.path.exists(env_path) and os.path.exists(env_example_path):
        print("[*] First-time setup: generating .env file with secure secret key...")
        with open(env_example_path, "r") as f:
            content = f.read()
        secure_key = secrets.token_hex(32)
        content = content.replace("replace_this_with_a_secure_random_key_of_at_least_32_chars", secure_key)
        with open(env_path, "w") as f:
            f.write(content)
            
    load_dotenv(env_path)

def create_app():
    """Application factory for TypeMeter Flask GUI Server."""
    init_dotenv()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gui_dir = os.path.join(script_dir, "gui")
    
    app = Flask(__name__, static_folder=gui_dir, static_url_path="")
    
    # Enable reverse proxy support for HTTPS headers (Render, Heroku, Nginx)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    
    # Configure Flask Session signing & Production Safety
    is_prod = (os.environ.get("ENV") == "production")
    if is_prod:
        secret = os.environ.get("SECRET_KEY")
        if not secret:
            raise RuntimeError(
                "CRITICAL SECURITY CONFIGURATION ERROR: SECRET_KEY environment variable MUST be explicitly set in production (ENV=production)."
            )
        app.config["SECRET_KEY"] = secret
        app.config["DEBUG"] = False
    else:
        app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
    
    # Configure cookie parameters
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = is_prod
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    
    # Structured Logging Setup
    import logging
    import time
    logging.basicConfig(
        level=logging.INFO if is_prod else logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    @app.before_request
    def start_timer():
        from flask import g
        g.start_time = time.time()

    @app.before_request
    def log_proxy_headers():
        from flask import current_app
        current_app.logger.info(
            f"X-Forwarded-Proto={request.headers.get('X-Forwarded-Proto')}, "
            f"X-Forwarded-Host={request.headers.get('X-Forwarded-Host')}, "
            f"X-Forwarded-For={request.headers.get('X-Forwarded-For')}, "
            f"request.scheme={request.scheme}, "
            f"request.url={request.url}"
        )

    @app.after_request
    def log_request(response):
        from flask import g
        if hasattr(g, "start_time"):
            duration_ms = round((time.time() - g.start_time) * 1000, 2)
            client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
            app.logger.info(f"{request.method} {request.path} {response.status_code} - {duration_ms}ms ({client_ip})")
        return response

    # Security Response Headers Middleware
    @app.after_request
    def add_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "img-src 'self' data:;"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Generic Error Handler preventing 500 info disclosure
    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.error(f"Unhandled Server Error: {e}", exc_info=True)
        if request.path.startswith("/api/") or request.path.startswith("/auth/"):
            return jsonify({"error": "An internal server error occurred."}), 500
        return "<h1>500 Internal Server Error</h1><p>An unexpected error occurred. Please try again later.</p>", 500

    # Register blueprints
    from auth import auth_bp, init_oauth
    app.register_blueprint(auth_bp, url_prefix="/auth")
    init_oauth(app)
    
    # Initialize DB schemas
    db_path = os.path.join(script_dir, "typemeter.db")
    app.config["DATABASE"] = db_path
    db = typemeter_db.get_db(db_path)
    try:
        typemeter_db.cleanup_sessions(db)
    finally:
        db.close()
        
    # --- Request-Bound Database Connection ---
    @app.before_request
    def open_db_connection():
        from flask import g
        g.db = typemeter_db.get_db(app.config["DATABASE"])
        
    @app.teardown_appcontext
    def close_db_connection(exception):
        from flask import g
        db = getattr(g, 'db', None)
        if db is not None:
            db.close()

    # --- Health Check Endpoint ---
    @app.route("/healthz", methods=["GET"])
    @app.route("/health", methods=["GET"])
    def health_check():
        """Health check endpoint for production platform monitoring."""
        try:
            db = typemeter_db.get_db(app.config["DATABASE"])
            cursor = db.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            db.close()
            return jsonify({
                "status": "healthy",
                "database": "connected",
                "environment": os.environ.get("ENV", "development"),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }), 200
        except Exception as e:
            app.logger.error(f"Health check database connection failure: {e}")
            return jsonify({
                "status": "unhealthy",
                "database": "disconnected",
                "error": "Database ping failed"
            }), 503

    # --- CSRF Protection Middleware ---
    @app.before_request
    def csrf_protect():
        # Ensure session has a CSRF token
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
            
        # Validate state-changing operations
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            # Exclude Google callback since it handles its own OAuth state verification
            if request.path == "/auth/google/callback":
                return
                
            client_csrf = request.headers.get("X-CSRF-Token")
            server_csrf = session.get("csrf_token")
            
            if not client_csrf or not server_csrf or not hmac.compare_digest(client_csrf, server_csrf):
                return jsonify({"error": "CSRF token missing or invalid."}), 403

    # --- Identity Resolution Logic ---
    def resolve_identity_id():
        """
        Resolves identity: checks for a logged-in session first,
        falling back to the anonymous cookie. Returns (identity_id, set_cookie_needed).
        """
        from flask import g
        db = g.db
        sess_id = session.get("session_id")
        
        # 1. Attempt session lookup
        if sess_id:
            sess = typemeter_db.get_session(db, sess_id)
            if sess:
                typemeter_db.touch_session(db, sess_id)
                return str(sess["user_id"]), False
                
        # 2. Fall back to anonymous cookie lookup
        anon_cookie = request.cookies.get("identity_id")
        if anon_cookie:
            return anon_cookie, False
            
        # 3. Generate new anonymous identity
        new_uuid = str(uuid.uuid4())
        return new_uuid, True

    # --- API Core Endpoints ---
    @app.route("/auth/csrf-token", methods=["GET"])
    def get_csrf_token():
        """Returns the current session's CSRF token."""
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return jsonify({"csrf_token": session["csrf_token"]})

    @app.route("/api/words", methods=["GET"])
    def get_words():
        difficulty = request.args.get("difficulty", "easy")
        count_str = request.args.get("count", "25")
        try:
            count = int(count_str)
        except ValueError:
            count = 25
            
        identity_id, set_cookie = resolve_identity_id()
        from flask import g
        db = g.db
        words = typemeter_db.backend_select_words(db, difficulty, count, identity_id)
        
        response = make_response(jsonify(words))
        if set_cookie:
            response.set_cookie("identity_id", identity_id, max_age=31536000, httponly=True, path="/")
        return response

    @app.route("/api/mistakes", methods=["POST"])
    def post_mistakes():
        records = request.get_json() or []
        identity_id, set_cookie = resolve_identity_id()
        
        from flask import g
        db = g.db
        typemeter_db.ingest_mistakes(db, identity_id, records)
        
        response = make_response("", 204)
        if set_cookie:
            response.set_cookie("identity_id", identity_id, max_age=31536000, httponly=True, path="/")
        return response

    # --- Authentication Middleware Decorator ---
    from functools import wraps
    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import g
            sess_id = session.get("session_id")
            if not sess_id:
                return jsonify({"error": "Authentication required."}), 401
            sess = typemeter_db.get_session(g.db, sess_id)
            if not sess:
                return jsonify({"error": "Session expired or invalid."}), 401
            g.current_user_id = sess["user_id"]
            return f(*args, **kwargs)
        return decorated_function

    @app.route("/api/save_session", methods=["POST"])
    def post_save_session():
        from flask import g
        data = request.get_json() or {}
        identity_id, set_cookie = resolve_identity_id()
        
        sess_id = session.get("session_id")
        user_id = None
        if sess_id:
            sess = typemeter_db.get_session(g.db, sess_id)
            if sess:
                user_id = sess["user_id"]
                
        try:
            rec_id = typemeter_db.save_typing_session(g.db, identity_id, user_id, data)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

        response = make_response(jsonify({"status": "success", "session_id": rec_id}), 201)
        if set_cookie:
            response.set_cookie("identity_id", identity_id, max_age=31536000, httponly=True, path="/")
        return response

    @app.route("/api/history", methods=["GET"])
    @login_required
    def get_history():
        from flask import g
        try:
            limit = min(int(request.args.get("limit", 50)), 100)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 50, 0
            
        sessions, total_count = typemeter_db.get_user_history(g.db, g.current_user_id, limit=limit, offset=offset)
        return jsonify({
            "sessions": sessions,
            "total_count": total_count,
            "limit": limit,
            "offset": offset
        })

    @app.route("/api/records", methods=["GET"])
    @login_required
    def get_records():
        from flask import g
        records = typemeter_db.get_user_records(g.db, g.current_user_id)
        return jsonify(records)

    # --- Static Files Routing ---
    @app.route("/")
    @app.route("/index.html")
    def gui_index():
        return send_from_directory(gui_dir, "index.html")

    @app.route("/history")
    @app.route("/history.html")
    def gui_history():
        return send_from_directory(gui_dir, "history.html")
        
    @app.route("/<path:path>")
    def gui_static(path):
        return send_from_directory(gui_dir, path)
        
    return app

def start_dev_server(app, port):
    """Runs the Flask application in dev mode on localhost."""
    # Suppress standard logging for static files
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)
    
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    print("==================================================")
    print("           TypeMeter Local GUI Server             ")
    print("==================================================")
    
    app = create_app()
    
    try:
        port = get_free_port(START_PORT)
    except OSError as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)
        
    url = f"http://127.0.0.1:{port}/index.html"
    
    # Start Flask dev server in a background thread
    server_thread = threading.Thread(target=start_dev_server, args=(app, port), daemon=True)
    server_thread.start()
    
    print(f"[*] Served via Flask application factory.")
    print(f"[*] App URL: {url}")
    print("[*] Launching system default browser...")
    
    webbrowser.open(url)
    
    print("\n--------------------------------------------------")
    print(" Press Ctrl+C in this terminal to stop the server.")
    print("--------------------------------------------------\n")
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Shutting down TypeMeter Local GUI Server. Goodbye!")
        sys.exit(0)
