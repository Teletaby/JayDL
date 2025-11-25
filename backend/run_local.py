#!/usr/bin/env python3
"""
Local development server for JayDL
Run this file to start the backend locally
"""

import os
import sys
import webbrowser
from app import app

def main():
    print("Starting JayDL Backend Locally...")
    print("Installing dependencies...")
    
    # Install requirements if not already installed
    try:
        import flask
        import yt_dlp
        print("Dependencies already installed")
    except ImportError:
        print("Installing missing dependencies...")
        os.system("pip install -r requirements.txt")
    
    print("Starting Flask development server...")
    print("Backend will be available at: http://localhost:5000")
    print("API endpoints:")
    print("   - http://localhost:5000/api/health")
    print("   - http://localhost:5000/api/info")
    print("   - http://localhost:5000/api/download")
    print("\nPress Ctrl+C to stop the server")
    print("-" * 50)
    
    # Start the Flask development server
    app.run(host='0.0.0.0', port=5000, debug=True)

if __name__ == '__main__':
    main()