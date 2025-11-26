import http.server
import socketserver
import os

PORT = int(os.environ.get('PORT', 3000))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=".", **kwargs)

def start_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Frontend server running on port {PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    start_server()