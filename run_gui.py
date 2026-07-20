#!/usr/bin/env python3
import http.server
import socketserver
import webbrowser
import threading
import os
import sys
import socket
from urllib.parse import urlparse, parse_qs
import json
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

class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """A SimpleHTTPRequestHandler that suppresses standard logger output, handles session cookies, and implements the API endpoints."""
    def log_message(self, format, *args):
        # Disable logging for static files to keep standard output tidy.
        pass

    def get_db(self):
        return typemeter_db.get_db("typemeter.db")

    def resolve_identity_id(self):
        if hasattr(self, '_resolved_identity_id'):
            return self._resolved_identity_id
            
        cookie_header = self.headers.get('Cookie', '')
        cookies = {}
        for item in cookie_header.split(';'):
            item = item.strip()
            if '=' in item:
                k, v = item.split('=', 1)
                cookies[k] = v
                
        if 'identity_id' in cookies:
            self._resolved_identity_id = cookies['identity_id']
            self._cookie_already_present = True
        else:
            import uuid
            self._resolved_identity_id = str(uuid.uuid4())
            self._cookie_already_present = False
            
        return self._resolved_identity_id

    def end_headers(self):
        identity_id = self.resolve_identity_id()
        if not getattr(self, '_cookie_already_present', False):
            self.send_header('Set-Cookie', f"identity_id={identity_id}; Max-Age=31536000; HttpOnly; Path=/")
        super().end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/api/words':
            params = parse_qs(parsed_path.query)
            difficulty = params.get('difficulty', ['easy'])[0]
            count_str = params.get('count', ['25'])[0]
            try:
                count = int(count_str)
            except ValueError:
                count = 25
                
            identity_id = self.resolve_identity_id()
            
            # Select words using mistake weightings
            conn = self.get_db()
            try:
                words = typemeter_db.backend_select_words(conn, difficulty, count, identity_id)
            finally:
                conn.close()
                
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(words).encode('utf-8'))
        else:
            super().do_GET()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == '/api/mistakes':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                records = json.loads(post_data.decode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid JSON")
                return
                
            identity_id = self.resolve_identity_id()
            
            conn = self.get_db()
            try:
                typemeter_db.ingest_mistakes(conn, identity_id, records)
            finally:
                conn.close()
                
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def start_server(port, directory):
    """Runs a local socket server on the given port serving files in directory."""
    # Ensure correct working directory when serving
    class Handler(QuietHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)
            
    # Allow port reuse to avoid binding issues immediately after restarts
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
            print(f"[*] Local HTTP Server started successfully.")
            httpd.serve_forever()
    except Exception as e:
        print(f"[!] Server Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    # Locate GUI folder
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Verify that the gui folder exists
    gui_dir = os.path.join(script_dir, "gui")
    if not os.path.isdir(gui_dir):
        print(f"[!] Error: Could not locate 'gui' subdirectory in {script_dir}", file=sys.stderr)
        sys.exit(1)

    print("==================================================")
    print("           TypeMeter Local GUI Server             ")
    print("==================================================")
    
    try:
        port = get_free_port(START_PORT)
    except OSError as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)
        
    url = f"http://127.0.0.1:{port}/index.html"
    
    # Start the server in a separate background daemon thread
    server_thread = threading.Thread(target=start_server, args=(port, gui_dir), daemon=True)
    server_thread.start()
    
    print(f"[*] Serving GUI directory at: {gui_dir}")
    print(f"[*] App URL: {url}")
    print("[*] Launching system default browser...")
    
    # Launch default web browser targeting our local port server
    webbrowser.open(url)
    
    print("\n--------------------------------------------------")
    print(" Press Ctrl+C in this terminal to stop the server.")
    print("--------------------------------------------------\n")
    
    # Keep main thread alive
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Shutting down TypeMeter Local GUI Server. Goodbye!")
        sys.exit(0)
