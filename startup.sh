#!/bin/bash
# JayDL Local Development Startup Script

echo "🚀 Starting JayDL Development Environment..."

# Check if .env exists
if [ ! -f "backend/.env" ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp backend/.env.example backend/.env
    echo "📝 Please edit backend/.env with your RapidAPI credentials"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r backend/requirements.txt

# Create downloads directory
mkdir -p backend/downloads

# Start backend
echo "🔧 Starting backend server..."
cd backend
gunicorn app:app --bind 0.0.0.0:5000 --reload &
BACKEND_PID=$!
cd ..

# Start frontend
echo "🎨 Starting frontend server..."
cd frontend
python local-server.py &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ JayDL is running!"
echo "📱 Frontend: http://localhost:8000"
echo "⚙️  Backend: http://localhost:5000"
echo "🏥 Health Check: http://localhost:5000/api/health"
echo ""
echo "Press Ctrl+C to stop all services..."

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID
