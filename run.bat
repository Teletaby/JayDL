@echo off
REM JayDL - Complete Setup and Launch Script
REM This script will:
REM 1. Check and install Node.js if needed
REM 2. Install all dependencies
REM 3. Launch all services

echo =========================================
echo    JayDL Setup and Launch
echo =========================================
echo.

REM Check if Node.js is installed
node -v >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Node.js is not installed
    echo.
    echo Please download and install Node.js from:
    echo https://nodejs.org/
    echo.
    echo After installing Node.js, run this script again.
    pause
    exit /b 1
)

echo ✅ Node.js is installed
node -v
echo.

REM Install chatbot dependencies if needed
if not exist "chatbot\node_modules" (
    echo 📦 Installing chatbot dependencies...
    cd chatbot
    call npm install
    cd ..
    echo ✅ Chatbot dependencies installed
    echo.
)

REM Run main launcher
echo 🚀 Starting JayDL...
python main.py

pause
