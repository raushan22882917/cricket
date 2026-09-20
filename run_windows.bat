@echo off
title Cricket AI Broadcaster
echo ===================================================
echo       Cricket AI Live Commentary Broadcaster
echo ===================================================
echo.

:: Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to PATH!
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check the box "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Check or create virtual environment
if not exist ".venv" (
    echo [*] Creating virtual environment (.venv)...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Install/update dependencies
echo [*] Checking and installing dependencies...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo.
echo ===================================================
echo [*] Starting Cricket AI Broadcaster...
echo [*] Web UI will be available at: http://localhost:8088
echo [*] Press Ctrl+C in this window to stop the server.
echo ===================================================
echo.

:: Open browser automatically after 2 seconds
start "" http://localhost:8088

:: Start server
python server.py

pause
