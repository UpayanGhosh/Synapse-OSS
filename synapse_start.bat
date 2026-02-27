@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
setlocal EnableDelayedExpansion

REM Synapse Start Script for Windows (Batch)
REM This script starts all the necessary background services for Synapse to run.

echo.
echo Starting Synapse services...
echo.

REM Get project root
set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

REM 1. Start Docker Container
echo [1/4] Starting Qdrant...
docker start antigravity_qdrant >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo    [OK] Started.
) else (
    echo    [OK] Already running or not found.
)

REM 2. Start Ollama
echo [2/4] Starting Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if %ERRORLEVEL% NEQ 0 (
    start /B ollama serve >nul 2>&1
    echo    [OK] Started.
    REM Pull embedding model in background (no-op if already present)
    start /B ollama pull nomic-embed-text >nul 2>&1
) else (
    echo    [OK] Already running.
)

REM 3. Start API Gateway
echo [3/4] Starting API Gateway...
netstat -ano | findstr ":8000" | find "LISTENING" >nul
if %ERRORLEVEL% NEQ 0 (
    if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
        mkdir "%USERPROFILE%\.openclaw\logs" >nul 2>&1
        REM Write a temp launcher to avoid nested-quote breakage in cmd /c "..."
        (
            echo @echo off
            echo set PYTHONUTF8=1
            echo set PYTHONIOENCODING=utf-8
            echo "%PROJECT_ROOT%\.venv\Scripts\python.exe" -X utf8 -m uvicorn --app-dir "%PROJECT_ROOT%\workspace" sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000 --workers 1 ^>^> "%USERPROFILE%\.openclaw\logs\gateway.log" 2^>^&1
        ) > "%TEMP%\_synapse_gateway.bat"
        start "Synapse API Gateway" /B cmd /c "%TEMP%\_synapse_gateway.bat"
        echo    [OK] Started. (log: %USERPROFILE%\.openclaw\logs\gateway.log)
    ) else (
        echo    [X] ERROR: Python virtual environment not found at %PROJECT_ROOT%\.venv
    )
) else (
    echo    [OK] Already running.
)

REM 4. Start OpenClaw Gateway
echo [4/4] Starting OpenClaw Gateway...
netstat -ano | findstr ":18789" | find "LISTENING" >nul
if %ERRORLEVEL% NEQ 0 (
    start /B openclaw gateway >nul 2>&1
    echo    [OK] Started.
) else (
    echo    [OK] Already running.
)

echo.
echo Synapse is starting up. It may take a moment.
echo You can now message Synapse on WhatsApp.
