@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM Synapse Onboard Script for Windows (Batch)
REM This script guides a user through the initial setup and launch of Synapse.

echo.
echo =======================================
echo    Synapse Onboard - Let's Get Started!
echo =======================================
echo.

echo Hi there! I'm going to guide you through setting up Synapse on Windows.
echo This will only take a few minutes.
echo.
pause

echo.
echo Step 1: Checking your tools...
echo.

REM Check Git
where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [X] git is NOT installed
    set "MISSING=1"
) else (
    echo    [OK] git is installed
)

REM Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    where python3 >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo    [X] python is NOT installed
        set "MISSING=1"
    ) else (
        echo    [OK] python is installed
    )
) else (
    echo    [OK] python is installed
)

REM Check Docker
where docker >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [X] docker is NOT installed
    set "MISSING=1"
) else (
    echo    [OK] docker is installed
)

REM Check OpenClaw
where openclaw >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [X] openclaw is NOT installed
    set "MISSING=1"
) else (
    echo    [OK] openclaw is installed
)

if defined MISSING (
    echo.
    echo ERROR: Some tools are missing.
    echo.
    echo Please install the missing tools from HOW_TO_RUN.md and try again.
    echo.
    pause
    exit /b 1
)

REM Check Docker Desktop is running
echo.
echo    - Docker Desktop Status: Checking...
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [X] Not responding
    echo.
    echo ERROR: Docker is not running. Please start Docker Desktop and wait for it
    echo to fully initialize, then run this script again.
    echo.
    pause
    exit /b 1
) else (
    echo [OK] Running
)

REM Check .env file
if not exist ".env" (
    echo.
    echo ERROR: No .env file found.
    echo.
    echo Run this first:
    echo    copy .env.example .env
    echo Then open .env and add your GEMINI_API_KEY.
    echo.
    pause
    exit /b 1
)

REM Step 2: Set up Python environment
echo.
echo Step 2: Setting up Python...
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    echo Installing dependencies...
    call .venv\Scripts\pip.exe install -r requirements.txt
    echo [OK] Virtual environment ready.
) else (
    echo [OK] Virtual environment already exists.
)

REM Step 3: Set up Docker
echo.
echo Step 3: Setting up Docker...
echo.

docker start antigravity_qdrant >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    docker run -d --name antigravity_qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant >nul 2>&1
    echo [OK] Created and started Qdrant container.
) else (
    echo [OK] Started Qdrant container.
)

REM Step 4: Link WhatsApp
echo.
echo Step 4: Linking WhatsApp...
echo.
echo    1. Open WhatsApp on your phone
echo    2. Go to Settings - Linked Devices
echo    3. Tap 'Link a Device'
echo    4. Scan the QR code below
echo.
pause

echo.
echo Scanning QR code now...
echo.
openclaw channels login --channel whatsapp --verbose
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: WhatsApp login failed.
    echo.
    echo If you have not set up OpenClaw before, run this first:
    echo    openclaw setup --wizard
    echo Then select WhatsApp when prompted.
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] WhatsApp linked!
echo.

REM Step 5: Get phone number
echo.
echo Step 5: Enter your phone number...
echo.

echo This lets Synapse know it is YOU messaging it.
echo Enter your number with country code (e.g., +15551234567)
echo.

set /p PHONE_NUMBER="Your phone number: "

REM Validate phone number format
echo %PHONE_NUMBER% | findstr /R "^+[0-9][0-9]*$" >nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Invalid format! Use E.164 format like: +15551234567
    pause
    exit /b 1
)

echo.
echo Saving phone number to OpenClaw config...
openclaw config set channels.whatsapp.allowFrom "[\"%PHONE_NUMBER%\"]" --json >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    openclaw config set channels.whatsapp.allowFrom "[\"%PHONE_NUMBER%\"]" >nul 2>&1
)
echo [OK] Phone number saved: %PHONE_NUMBER%

REM Step 6: Configure OpenClaw to use Synapse workspace
echo.
echo Step 6: Configuring OpenClaw workspace...
echo.

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "SYNAPSE_WORKSPACE=%PROJECT_ROOT%\workspace"

openclaw config set agents.defaults.workspace "%SYNAPSE_WORKSPACE%" >nul 2>&1
echo [OK] Workspace set to: %SYNAPSE_WORKSPACE%

REM Step 7: Start services
echo.
echo Step 7: Starting All Synapse Services...
echo.

call synapse_start.bat

echo.
echo ========================================
echo [OK] Synapse is running!
echo ========================================
echo.
echo How to Chat with Synapse:
echo.
echo    1. Open WhatsApp on your phone
echo    2. Find 'Message yourself' at the top of your chat list
echo    3. Send a message to start the conversation!
echo.
echo Try sending: Hello or What is up?
echo.
echo Synapse will reply. Have fun!
echo.
pause
