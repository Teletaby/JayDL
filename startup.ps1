# JayDL Local Development Startup Script (Windows)

Write-Host "🚀 Starting JayDL Development Environment..." -ForegroundColor Green

# Check if .env exists
if (-not (Test-Path "backend\.env")) {
    Write-Host "⚠️  .env file not found. Copying from .env.example..." -ForegroundColor Yellow
    Copy-Item "backend\.env.example" "backend\.env"
    Write-Host "📝 Please edit backend\.env with your RapidAPI credentials" -ForegroundColor Cyan
    exit 1
}

# Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Python is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Install dependencies
Write-Host "📦 Installing dependencies..." -ForegroundColor Cyan
python -m pip install -r backend\requirements.txt

# Create downloads directory
if (-not (Test-Path "backend\downloads")) {
    New-Item -ItemType Directory -Path "backend\downloads" | Out-Null
    Write-Host "✅ Created downloads directory" -ForegroundColor Green
}

# Start backend
Write-Host "🔧 Starting backend server..." -ForegroundColor Cyan
Push-Location backend
$backendProcess = Start-Process python -ArgumentList "-m flask run --host=0.0.0.0 --port=5000" -PassThru -NoNewWindow
Pop-Location

# Wait a bit for backend to start
Start-Sleep -Seconds 2

# Start frontend
Write-Host "🎨 Starting frontend server..." -ForegroundColor Cyan
Push-Location frontend
$frontendProcess = Start-Process python -ArgumentList "local-server.py" -PassThru -NoNewWindow
Pop-Location

Write-Host ""
Write-Host "✅ JayDL is running!" -ForegroundColor Green
Write-Host "📱 Frontend: http://localhost:8000" -ForegroundColor Yellow
Write-Host "⚙️  Backend: http://localhost:5000" -ForegroundColor Yellow
Write-Host "🏥 Health Check: http://localhost:5000/api/health" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press Ctrl+C to stop services and close windows..." -ForegroundColor Magenta

# Keep script running
while ($backendProcess.HasExited -eq $false -and $frontendProcess.HasExited -eq $false) {
    Start-Sleep -Seconds 1
}

Write-Host "Services stopped." -ForegroundColor Yellow
