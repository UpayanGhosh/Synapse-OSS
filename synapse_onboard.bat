@echo off
REM Synapse Onboard Script for Windows (Batch)
REM This script guides a user through the initial setup and launch of Synapse.

echo.
echo 🤖 =======================================
echo    Synapse Onboard - Let's Get Started!
echo ========================================
echo.

echo Hi there! I'm going to guide you through setting up Synapse on Windows.
echo This will only take a few minutes.
echo.
pause

echo.
echo 🔍 Step 1: Checking your tools...
echo.

REM Check Git
where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    ✗ git is NOT installed
    set "MISSING=1"
) else (
    echo    ✓ git is installed
)

REM Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    where python3 >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo    ✗ python is NOT installed
        set "MISSING=1"
    ) else (
        echo    ✓ python is installed
    )
) else (
    echo    ✓ python is installed
)

REM Check Docker
where docker >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    ✗ docker is NOT installed
    set "MISSING=1"
) else (
    echo    ✓ docker is installed
)

REM Check OpenClaw
where openclaw >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    ✗ openclaw is NOT installed
    set "MISSING=1"
) else (
    echo    ✓ openclaw is installed
)

if defined MISSING (
    echo.
    echo ❌ Oops! Some tools are missing.
    echo.
    echo Please install the missing tools from the links in HOW_TO_RUN.md and try again.
    echo.
    pause
    exit /b 1
)

REM Check Docker Desktop is running
echo    - Docker Desktop Status: Checking...
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ✗ Not responding
    echo.
    echo Error: The Docker daemon isn^t running. Please start Docker Desktop and wait for it
    echo to be fully initialized, then run this script again.
    echo.
    pause
    exit /b 1
) else (
    echo ✓ Running
)

REM Check .env file
if not exist ".env" (
    echo.
    echo ❌ No .env file found.
    echo.
    echo Run this first:
    echo    copy .env.example .env
    echo Then open .env and add your GEMINI_API_KEY (at minimum).
    echo.
    pause
    exit /b 1
)

REM Check for API key
findstr /C:"GEMINI_API_KEY=" .env >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ⚠️  Warning: GEMINI_API_KEY does not appear to be set in your .env file.
    echo    Synapse will start but LLM calls will fail until you add an API key.
    echo.
)

REM Step 2: Set up Python environment
echo.
echo 🐍 Step 2: Setting up Python...
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    echo Installing dependencies...
    call .venv\Scripts\pip.exe install -r requirements.txt
    echo ✓ Virtual environment ready.
) else (
    echo ✓ Virtual environment already exists.
)

REM Step 3: Set up Docker
echo.
echo 🐳 Step 3: Setting up Docker...
echo.

docker start antigravity_qdrant >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✓ Started Qdrant container.
) else (
    docker run -d --name antigravity_qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant >nul 2>&1
    echo ✓ Created and started Qdrant container.
)

REM Step 4: Link WhatsApp
echo.
echo 📱 Step 4: Linking WhatsApp...
echo.

echo Opening WhatsApp Web...
start https://web.whatsapp.com

echo.
echo Please scan the QR code with your phone to link WhatsApp.
echo.
pause

REM Step 5: Start services
echo.
echo 🚀 Step 5: Starting All Synapse Services...
echo.

call synapse_start.bat

echo.
echo ========================================
echo ✓ Synapse is running!
echo ========================================
echo.
echo Step 4: How to Chat with Synapse
echo.
echo To chat with Synapse:
echo    1. Open WhatsApp on your phone
echo    2. Find 'Message yourself' at the top of your chat list
echo    3. Send a message to start the conversation!
echo.
echo Try sending: "Hello" or "What's up?"
echo.
echo Synapse will reply! Have fun! 🤖
echo.
pause
