import os
import sys
from run_gui import create_app
from waitress import serve

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port_str = os.environ.get("PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000
        
    print(f"[*] Serving TypeMeter production server via Waitress WSGI...")
    print(f"[*] Binding to {host}:{port}")
    serve(app, host=host, port=port)
