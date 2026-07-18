#!/usr/bin/env python3
import http.server
import socketserver
import webbrowser
import threading
import os
import sys
import socket

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
    """A SimpleHTTPRequestHandler that suppresses standard logger output to keep console clean."""
    def log_message(self, format, *args):
        # Disable logging for static files to keep standard output tidy.
        pass

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
