import http.server
import socketserver
import os
import sys

# Set port - use 8000 by default for local development
# Note: Explicitly use 8000 to avoid conflicts with backend on 5000
PORT = 8000
if 'FRONTEND_PORT' in os.environ:
    PORT = int(os.environ.get('FRONTEND_PORT', 8000))

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)
    
    def log_message(self, format, *args):
        """Override to print to stdout"""
        print(f"[Frontend] {format % args}", flush=True)

def start_server():
    try:
        handler = Handler
        with socketserver.TCPServer(("", PORT), handler) as httpd:
            print(f"Frontend server running on http://localhost:{PORT}", flush=True)
            sys.stdout.flush()
            httpd.serve_forever()
    except OSError as e:
        print(f"Error: Failed to start server on port {PORT}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

if __name__ == "__main__":
    start_server()