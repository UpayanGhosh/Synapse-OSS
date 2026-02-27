@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
setlocal EnableDelayedExpansion

REM Synapse Start Script for Windows (Batch)
REM Handles both first-run setup and subsequent starts.

REM Get project root
set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

echo.
echo =======================================
echo    Synapse
echo =======================================
echo.

REM --- Guard: .env must exist ---
if not exist "%PROJECT_ROOT%\.env" (
    echo [X] No .env file found.
    echo.
    echo     Run this first:
    echo        copy "%PROJECT_ROOT%\.env.example" "%PROJECT_ROOT%\.env"
    echo     Then open .env and add your GEMINI_API_KEY.
    echo.
    pause
    exit /b 1
)

REM --- Guard: Docker must be running ---
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [X] Docker is not running. Please start Docker Desktop and try again.
    echo.
    pause
    exit /b 1
)

REM --- First-run: Python environment ---
if not exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    echo [SETUP] First run detected - setting up Python environment...
    echo.

    where python >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo [X] Python is not installed. Install from https://python.org and try again.
        pause
        exit /b 1
    )

    python -m venv "%PROJECT_ROOT%\.venv"
    if %ERRORLEVEL% NEQ 0 (
        echo [X] Failed to create virtual environment.
        pause
        exit /b 1
    )

    echo Installing dependencies (this takes a minute on first run)...
    call "%PROJECT_ROOT%\.venv\Scripts\pip.exe" install -r "%PROJECT_ROOT%\requirements.txt"
    if %ERRORLEVEL% NEQ 0 (
        echo [X] pip install failed. Check requirements.txt and try again.
        pause
        exit /b 1
    )

    echo Installing Playwright browser (Chromium)...
    call "%PROJECT_ROOT%\.venv\Scripts\python.exe" -m playwright install chromium
    if %ERRORLEVEL% NEQ 0 (
        echo [--] Playwright install failed - /browse tool will not work.
        echo      Try manually: python -m playwright install chromium
    )

    echo.
    echo [OK] Python environment ready.
    echo.
)

REM --- 1. Qdrant ---
echo [1/4] Starting Qdrant...
docker start antigravity_qdrant >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo    [OK] Started.
) else (
    docker run -d --name antigravity_qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo    [OK] Created and started.
    ) else (
        echo    [--] Qdrant unavailable - vector search will be disabled.
    )
)

REM --- 2. Ollama ---
echo [2/4] Starting Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if %ERRORLEVEL% NEQ 0 (
    where ollama >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        start "Ollama" /min ollama serve
        start "Ollama Pull" /min ollama pull nomic-embed-text
        echo    [OK] Started.
    ) else (
        echo    [--] Ollama not installed - local embedding and The Vault will be disabled.
    )
) else (
    echo    [OK] Already running.
)

REM --- 3. API Gateway ---
echo [3/4] Starting API Gateway...
netstat -ano | findstr ":8000" | find "LISTENING" >nul
if %ERRORLEVEL% NEQ 0 (
    mkdir "%USERPROFILE%\.openclaw\logs" >nul 2>&1
    REM Write a temp launcher -- avoids nested-quote breakage in cmd /c "..."
    (
        echo @echo off
        echo set PYTHONUTF8=1
        echo set PYTHONIOENCODING=utf-8
        echo "%PROJECT_ROOT%\.venv\Scripts\python.exe" -X utf8 -m uvicorn --app-dir "%PROJECT_ROOT%\workspace" sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000 --workers 1 ^>^> "%USERPROFILE%\.openclaw\logs\gateway.log" 2^>^&1
    ) > "%TEMP%\_synapse_gateway.bat"
    start "Synapse API Gateway" /min cmd /c "%TEMP%\_synapse_gateway.bat"
    echo    [OK] Started. (log: %USERPROFILE%\.openclaw\logs\gateway.log)
) else (
    echo    [OK] Already running.
)

REM --- 4. OpenClaw Gateway ---
echo [4/4] Starting OpenClaw Gateway...
netstat -ano | findstr ":18789" | find "LISTENING" >nul
if %ERRORLEVEL% NEQ 0 (
    start "OpenClaw Gateway" /min openclaw gateway
    echo    [OK] Started.
) else (
    echo    [OK] Already running.
)

echo.
echo =======================================
echo [OK] Synapse is running!
echo =======================================
echo.
echo Open WhatsApp ^> Message Yourself ^> say hello!
echo.
echo To check the API gateway log:
echo    type "%USERPROFILE%\.openclaw\logs\gateway.log"
echo.
