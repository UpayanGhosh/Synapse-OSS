@echo off
REM Synapse Start Script for Windows (Batch)
REM This script starts all the necessary background services for Synapse to run.
REM It assumes you have already run the 'synapse_onboard.bat' script at least once.

echo.
echo 🚀 Starting Synapse services...
echo.

REM Get project root (directory where this script is located)
set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

REM 1. Start Docker Container
set /p qdrant_check=<nul
echo [1/4] Starting Qdrant...
docker start antigravity_qdrant >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo    ✓ Started.
) else (
    echo    ✓ Already running or not found.
)

REM 2. Start Ollama
echo [2/4] Starting Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if %ERRORLEVEL% NEQ 0 (
    start /B ollama serve >nul 2>&1
    echo    ✓ Started.
) else (
    echo    ✓ Already running.
)

REM 3. Start API Gateway
echo [3/4] Starting API Gateway...
netstat -ano | findstr ":8000" | find "LISTENING" >nul
if %ERRORLEVEL% NEQ 0 (
    if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
        cd /d "%PROJECT_ROOT%\workspace"
        start /B cmd /c ".venv\Scripts\python.exe -m uvicorn sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000 --workers 1" >nul 2>&1
        cd /d "%PROJECT_ROOT%"
        echo    ✓ Started.
    ) else (
        echo    ✗ ERROR: Could not find Python virtual environment. Cannot start gateway.
    )
) else (
    echo    ✓ Already running.
)

REM 4. Start OpenClaw Gateway
echo [4/4] Starting OpenClaw Gateway...
netstat -ano | findstr ":18789" | find "LISTENING" >nul
if %ERRORLEVEL% NEQ 0 (
    start /B openclaw gateway >nul 2>&1
    echo    ✓ Started.
) else (
    echo    ✓ Already running.
)

echo.
echo ✅ Synapse is starting up. It may take a moment.
echo You can now message Synapse on WhatsApp.
