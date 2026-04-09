@echo off
chcp 65001 >nul
title MDS Project System — Server

echo ================================================
echo  MDS Project System Server - Starting...
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

:: Install dependencies
echo Installing / verifying dependencies...
pip install flask flask-cors --quiet

echo.
echo ================================================
echo  Server starting on http://localhost:5000
echo  Share with colleagues:  http://YOUR-IP:5000
echo  Press Ctrl+C to stop
echo ================================================
echo.

:: Start server
python server.py --port 5000 --data-dir ./data

pause
