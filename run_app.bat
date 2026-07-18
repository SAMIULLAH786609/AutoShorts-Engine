@echo off
title AutoShorts App Launcher
color 0a

echo ==============================================================
echo          STARTING AUTOSHORTS ENGINE SAAS APPLICATION
echo ==============================================================
echo.

:: 1. Start FastAPI Backend in a new window
echo [1/3] Starting FastAPI Backend on Port 8000...
start "AutoShorts Backend" cmd /k "cd /d "%~dp0" && .venv\Scripts\activate && python -m uvicorn backend.main:app --port 8000"

:: Wait a brief moment for the backend to initialize
timeout /t 3 >nul

:: 2. Start React Frontend in a new window
echo [2/3] Starting Vite React Frontend on Port 5173...
start "AutoShorts Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

:: Wait for frontend to start
timeout /t 2 >nul

:: 3. Automatically open the Web App in your browser
echo [3/3] Opening application in your browser...
start http://localhost:5173

echo.
echo ==============================================================
echo  SUCCESS: Both Frontend and Backend are running in background!
echo  Keep the opened Command Prompt windows running.
echo ==============================================================
timeout /t 5
