#!/usr/bin/env python3
"""
Simple HTTP server for local frontend development
Run this file to serve the frontend locally
"""

import http.server
import socketserver
import webbrowser
import os

PORT = 3000
FRONTEND_DIR = '.'  # Current directory

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)
    
    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

def main():
    os.chdir(FRONTEND_DIR)
    
    print("Starting JayDL Frontend Locally...")
    print("Frontend will be available at: http://localhost:3000")
    print("Serving files from:", os.path.abspath(FRONTEND_DIR))
    print("Make sure backend is running at http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    print("-" * 50)
    
    # Auto-open browser
    webbrowser.open(f'http://localhost:{PORT}')
    
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Server running at http://localhost:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Server stopped")

if __name__ == '__main__':
    main()