@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM Synapse Onboard Script for Windows
REM Run this ONCE on first setup. For daily use, run synapse_start.bat instead.
REM
REM This script is a thin bootstrap launcher:
REM   1. Checks prerequisites (Python, Docker, Ollama)
REM   2. Creates .venv and installs dependencies
REM   3. Hands off to the Python wizard (synapse_cli.py onboard)
REM   4. Starts all services
REM   5. Pulls the required embedding model

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

echo.
echo =======================================
echo    Synapse Onboard
echo =======================================
echo.
echo This runs once to configure Synapse.
echo For daily use, run synapse_start.bat instead.
echo.
pause

REM ============================================================
REM Step 1: Check prerequisites
REM ============================================================
echo.
echo Step 1: Checking prerequisites...
echo.

set "MISSING="

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [X] Python not found. Install from https://python.org ^(check "Add to PATH"^)
    set "MISSING=1"
) else (
    for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PY_VER=%%V"
    echo    [OK] Python !PY_VER!
)

where docker >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [X] Docker not found. Install from https://docker.com
    set "MISSING=1"
) else (
    echo    [OK] Docker
)

REM Check for Ollama — first via PATH, then fallback to the known default install location.
REM "where ollama" only searches the PATH inherited when this process started, so it misses
REM Ollama if it was installed in the current session or lives only in the User PATH registry
REM entry that cmd.exe did not pick up. The fallback covers that case.
set "OLLAMA_EXE="
where ollama >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "OLLAMA_EXE=ollama"
) else if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    REM Add to PATH for this session so subsequent calls work without full path
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
)

if defined OLLAMA_EXE (
    echo    [OK] Ollama
) else (
    echo    Ollama not found. Installing automatically...
    echo    Downloading installer ^(this may take a moment^)...
    curl -L -o "%TEMP%\OllamaSetup.exe" "https://ollama.com/download/OllamaSetup.exe"
    if %ERRORLEVEL% NEQ 0 (
        echo    [X] Failed to download Ollama installer.
        echo        Install manually from https://ollama.com then run this script again.
        set "MISSING=1"
    ) else (
        echo    Running Ollama installer silently...
        "%TEMP%\OllamaSetup.exe" /S
        timeout /t 15 /nobreak >nul
        if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
            set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
            set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
            echo    [OK] Ollama installed successfully
        ) else (
            echo    [X] Ollama install did not complete. Install manually from https://ollama.com
            set "MISSING=1"
        )
    )
)

if defined MISSING (
    echo.
    echo ERROR: Install the missing tools above and run this script again.
    echo.
    pause
    exit /b 1
)

REM ============================================================
REM Step 2: Create .env from example if missing
REM ============================================================
echo.
echo Step 2: Checking .env...
echo.

if not exist "%PROJECT_ROOT%\.env" (
    if exist "%PROJECT_ROOT%\.env.example" (
        copy "%PROJECT_ROOT%\.env.example" "%PROJECT_ROOT%\.env" >nul
        echo    [OK] Created .env from .env.example
    ) else (
        type nul > "%PROJECT_ROOT%\.env"
        echo    [OK] Created empty .env
    )
) else (
    echo    [OK] .env already exists
)

REM ============================================================
REM Step 3: Python virtual environment + dependencies
REM ============================================================
echo.
echo Step 3: Setting up Python environment...
echo.

if not exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    echo    Creating virtual environment...
    python -m venv "%PROJECT_ROOT%\.venv"
    if %ERRORLEVEL% NEQ 0 (
        echo    [X] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo    [OK] Virtual environment created.
)

echo    Installing core dependencies ^(this takes a minute on first run^)...
call "%PROJECT_ROOT%\.venv\Scripts\pip.exe" install -r "%PROJECT_ROOT%\requirements.txt" -q
if %ERRORLEVEL% NEQ 0 (
    echo    [X] pip install failed. Check requirements.txt and try again.
    pause
    exit /b 1
)
echo    [OK] Core dependencies installed.

echo    Installing channel dependencies...
call "%PROJECT_ROOT%\.venv\Scripts\pip.exe" install -r "%PROJECT_ROOT%\requirements-channels.txt" -q
if %ERRORLEVEL% NEQ 0 (
    echo    [--] Channel dependencies failed ^(non-fatal^). Run manually if needed:
    echo         pip install -r requirements-channels.txt
)

echo    Installing Playwright browser ^(Chromium^)...
call "%PROJECT_ROOT%\.venv\Scripts\python.exe" -m playwright install chromium >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [--] Playwright install failed - /browse tool will not work.
) else (
    echo    [OK] Playwright ready.
)

REM ============================================================
REM Step 4: Python wizard — provider + channel setup
REM ============================================================
echo.
echo Step 4: Running Synapse setup wizard...
echo.
echo The wizard will guide you through:
echo   - Choosing your LLM provider ^(Anthropic, Google, OpenAI, etc.^)
echo   - Entering your API key^(s^)
echo   - Configuring your messaging channels ^(WhatsApp, Telegram, etc.^)
echo.

call "%PROJECT_ROOT%\.venv\Scripts\python.exe" -X utf8 ^
    "%PROJECT_ROOT%\workspace\synapse_cli.py" onboard

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [X] Wizard exited with an error. Fix the issue above and run this script again.
    echo.
    pause
    exit /b 1
)

REM ============================================================
REM Step 5: Start all services
REM ============================================================
echo.
echo Step 5: Starting services...
echo.

call "%PROJECT_ROOT%\synapse_start.bat"

REM ============================================================
REM Step 6: Pull the embedding model
REM ============================================================
echo.
echo Step 6: Pulling required embedding model ^(nomic-embed-text, ~900 MB^)...
echo This may take several minutes on first run. Please wait...
echo.
"%OLLAMA_EXE%" pull nomic-embed-text
echo    [OK] nomic-embed-text ready.

REM ============================================================
REM Done
REM ============================================================
echo.
echo ========================================
echo [OK] Onboarding complete!
echo ========================================
echo.
echo Next time, just run synapse_start.bat
echo.
pause
exit /b 0
