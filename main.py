#!/usr/bin/env python
"""
JayDL Main Launcher - Starts both backend and frontend servers
Run this file to start the entire application
"""

import subprocess
import sys
import os
import time
import signal
import threading
from pathlib import Path
from dotenv import load_dotenv

# Fix encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), 'backend', '.env'))

class JayDLLauncher:
    def __init__(self):
        self.root_dir = Path(__file__).parent
        self.backend_dir = self.root_dir / 'backend'
        self.frontend_dir = self.root_dir / 'frontend'
        self.chatbot_dir = self.root_dir / 'chatbot'
        self.processes = []
        self.monitor_threads = []
    
    def monitor_process_output(self, name, process):
        """Monitor and display output from a process"""
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    try:
                        print(f"[{name}] {line.rstrip()}")
                    except UnicodeDecodeError:
                        # Handle encoding issues gracefully
                        print(f"[{name}] (output encoding issue - process is running)")
                    sys.stdout.flush()
        except Exception as e:
            # Don't print error for normal process termination
            pass
        
    def check_dependencies(self):
        """Check if all required dependencies are available"""
        print("🔍 Checking dependencies...")
        
        # Check Python
        try:
            import_result = subprocess.run([sys.executable, '--version'], 
                                          capture_output=True, text=True)
            print(f"✅ Python {import_result.stdout.strip()}")
        except Exception as e:
            print(f"❌ Python check failed: {e}")
            return False
        
        # Check .env file
        env_file = self.backend_dir / '.env'
        if not env_file.exists():
            env_example = self.backend_dir / '.env.example'
            if env_example.exists():
                print("⚠️  .env file not found. Copying from .env.example...")
                import shutil
                shutil.copy(env_example, env_file)
                print("📝 Please edit backend/.env with your RapidAPI credentials")
                return False
            else:
                print("❌ .env file not found and .env.example not available")
                return False
        
        print("✅ Dependencies check passed")
        return True
    
    def install_dependencies(self):
        """Install Python dependencies"""
        print("📦 Installing Python dependencies...")
        try:
            requirements_file = self.backend_dir / 'requirements.txt'
            if requirements_file.exists():
                result = subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', '-q', '-r', str(requirements_file)],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    print("✅ Dependencies installed successfully")
                    return True
                else:
                    print(f"❌ Failed to install dependencies: {result.stderr}")
                    return False
            else:
                print("❌ requirements.txt not found")
                return False
        except Exception as e:
            print(f"❌ Error installing dependencies: {e}")
            return False
    
    def create_downloads_dir(self):
        """Create downloads directory if it doesn't exist"""
        downloads_dir = self.backend_dir / 'downloads'
        downloads_dir.mkdir(exist_ok=True)
        print("✅ Downloads directory ready")
    
    def start_backend(self):
        """Start the backend server"""
        print("🔧 Starting backend server...")
        try:
            # Start Flask app
            process = subprocess.Popen(
                [sys.executable, 'app.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(self.backend_dir)
            )
            
            self.processes.append(('backend', process))
            
            # Start monitoring thread
            monitor_thread = threading.Thread(
                target=self.monitor_process_output,
                args=('backend', process),
                daemon=True
            )
            monitor_thread.start()
            self.monitor_threads.append(monitor_thread)
            
            print(f"✅ Backend started (PID: {process.pid})")
            return True
        except Exception as e:
            print(f"❌ Failed to start backend: {e}")
            return False
    
    def start_frontend(self):
        """Start the frontend server"""
        print("🎨 Starting frontend server...")
        try:
            # Start frontend server
            process = subprocess.Popen(
                [sys.executable, 'local-server.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(self.frontend_dir)
            )
            
            self.processes.append(('frontend', process))
            
            # Start monitoring thread
            monitor_thread = threading.Thread(
                target=self.monitor_process_output,
                args=('frontend', process),
                daemon=True
            )
            monitor_thread.start()
            self.monitor_threads.append(monitor_thread)
            
            print(f"✅ Frontend started (PID: {process.pid})")
            return True
        except Exception as e:
            print(f"❌ Failed to start frontend: {e}")
            return False
    
    def start_chatbot(self):
        """Start the chatbot server"""
        print("💬 Starting chatbot server...")
        try:
            # Check if chatbot directory exists
            if not self.chatbot_dir.exists():
                print("⚠️  Chatbot directory not found. Skipping chatbot...")
                return True
            
            # Check if node_modules exists, if not try to install dependencies
            node_modules = self.chatbot_dir / 'node_modules'
            if not node_modules.exists():
                print("📦 Installing chatbot dependencies (first time)...")
                result = subprocess.run(
                    ['npm', 'install'],
                    cwd=str(self.chatbot_dir),
                    capture_output=True,
                    text=True
                )
                if result.returncode != 0:
                    print("⚠️  Warning: Failed to install chatbot dependencies")
                    print(f"   Error: {result.stderr}")
                    print("   Make sure Node.js is installed: https://nodejs.org/")
                    return True  # Don't fail, continue without chatbot
                print("✅ Chatbot dependencies installed")
            
            # Start chatbot server using node directly with better environment
            # Load chatbot .env variables
            chatbot_env = os.environ.copy()
            chatbot_env_file = self.chatbot_dir / '.env'
            if chatbot_env_file.exists():
                with open(chatbot_env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            chatbot_env[key.strip()] = value.strip()
            
            process = subprocess.Popen(
                ['node', 'server.js'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(self.chatbot_dir),
                env=chatbot_env
            )
            
            self.processes.append(('chatbot', process))
            
            # Start monitoring thread
            monitor_thread = threading.Thread(
                target=self.monitor_process_output,
                args=('chatbot', process),
                daemon=True
            )
            monitor_thread.start()
            self.monitor_threads.append(monitor_thread)
            
            print(f"✅ Chatbot started (PID: {process.pid})")
            
            # Give chatbot a moment to start
            time.sleep(1)
            return True
        except FileNotFoundError as e:
            print(f"⚠️  Node.js not found. Chatbot requires Node.js to run.")
            print("   Download from: https://nodejs.org/")
            print(f"   Error: {e}")
            return True  # Don't fail completely
        except Exception as e:
            print(f"⚠️  Failed to start chatbot: {e}")
            import traceback
            traceback.print_exc()
            return True  # Don't fail completely
    
    def print_status(self):
        """Print the application status"""
        print("\n" + "="*50)
        print("✅ JayDL is running!".center(50))
        print("="*50)
        print(f"📱 Frontend: http://localhost:8000")
        print(f"⚙️  Backend:  http://localhost:5000")
        print(f"💬 Chatbot:  http://localhost:3000")
        print(f"🏥 Health:   http://localhost:5000/api/health")
        print("="*50)
        print("Press Ctrl+C to stop all services...")
        print("="*50 + "\n")
    
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signal"""
        print("\n\n🛑 Shutting down JayDL...")
        self.stop_all()
        sys.exit(0)
    
    def stop_all(self):
        """Stop all running processes"""
        for name, process in self.processes:
            try:
                print(f"Stopping {name}...", end=" ")
                process.terminate()
                process.wait(timeout=5)
                print("✅")
            except subprocess.TimeoutExpired:
                print("Force stopping...", end=" ")
                process.kill()
                process.wait()
                print("✅")
            except Exception as e:
                print(f"❌ ({e})")
    
    def run(self):
        """Main launcher method"""
        # Register signal handlers
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        
        print("\n" + "="*50)
        print("🚀 Starting JayDL Development Environment".center(50))
        print("="*50 + "\n")
        
        # Check dependencies
        if not self.check_dependencies():
            print("❌ Dependency check failed. Exiting.")
            return False
        
        # Install dependencies
        if not self.install_dependencies():
            print("❌ Failed to install dependencies. Exiting.")
            return False
        
        # Create downloads directory
        self.create_downloads_dir()
        
        # Start servers
        if not self.start_backend():
            return False
        
        # Wait a bit for backend to initialize
        time.sleep(2)
        
        if not self.start_frontend():
            self.stop_all()
            return False
        
        # Wait a bit for frontend to initialize
        time.sleep(1)
        
        # Start chatbot (optional, doesn't fail if it doesn't work)
        self.start_chatbot()
        
        # Print status
        self.print_status()
        
        # Keep the launcher running
        try:
            while True:
                # Check if processes are still running
                active_processes = []
                for name, process in self.processes:
                    if process.poll() is None:  # Process is still running
                        active_processes.append((name, process))
                    else:
                        # Process has exited
                        print(f"⚠️  {name} process has exited unexpectedly")
                
                self.processes = active_processes
                
                # Count critical services (backend + frontend)
                critical_services = sum(1 for name, _ in self.processes if name in ['backend', 'frontend'])
                
                # If critical services have exited, shutdown everything
                if critical_services < 2:
                    print("❌ Critical service(s) have stopped. Shutting down...")
                    self.stop_all()
                    return False
                
                time.sleep(1)
        except KeyboardInterrupt:
            self.handle_shutdown(None, None)
        
        return True

if __name__ == '__main__':
    launcher = JayDLLauncher()
    success = launcher.run()
    sys.exit(0 if success else 1)
