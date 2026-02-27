@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM Synapse Onboard Script for Windows
REM Run this ONCE after copying Synapse files into ~/.openclaw/
REM (openclaw onboard must have already been completed before running this)

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

REM --- Step 1: Prerequisites ---
echo.
echo Step 1: Checking tools...
echo.

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [X] Python not installed. Install from https://python.org
    set "MISSING=1"
) else (
    echo    [OK] Python
)

where docker >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [X] Docker not installed. Install from https://docker.com
    set "MISSING=1"
) else (
    echo    [OK] Docker
)

where openclaw >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [X] OpenClaw not installed. Install from https://github.com/openclaw/openclaw/releases
    set "MISSING=1"
) else (
    echo    [OK] OpenClaw
)

where ollama >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [--] Ollama not installed -- local embedding and The Vault will be disabled
    echo         Install from https://ollama.com (optional)
) else (
    echo    [OK] Ollama
)

if defined MISSING (
    echo.
    echo ERROR: Install the missing tools above and run this script again.
    echo.
    pause
    exit /b 1
)

REM --- Step 2: .env check ---
echo.
echo Step 2: Checking config...
echo.

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

REM Warn if GEMINI_API_KEY is still the placeholder
findstr /C:"GEMINI_API_KEY=\"your_gemini" "%PROJECT_ROOT%\.env" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo WARNING: GEMINI_API_KEY is still the placeholder value.
    echo    Open .env and replace it with your real key from https://aistudio.google.com/
    echo.
    echo Press any key to continue anyway ^(LLM calls will fail until you fix this^)...
    pause >nul
) else (
    echo [OK] .env looks good.
)

REM --- Step 3: Phone number ---
echo.
echo Step 3: Your phone number...
echo.
echo Synapse uses this to know it is YOU messaging it.
echo Enter your number with country code, e.g. +15551234567
echo.

:phone_input
set /p PHONE_NUMBER="Your phone number: "

powershell -Command "if ('%PHONE_NUMBER%' -match '^\+[0-9]{10,15}$') { exit 0 } else { exit 1 }" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Invalid format. Use E.164 format starting with + and country code.
    echo   India: +919836939194   US: +15551234567   UK: +447912345678
    echo.
    goto phone_input
)

echo [OK] %PHONE_NUMBER%

REM --- Step 4: Configure OpenClaw ---
echo.
echo Step 4: Saving config to OpenClaw...
echo.

openclaw config set channels.whatsapp.allowFrom "[\"%PHONE_NUMBER%\"]" --json >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    openclaw config set channels.whatsapp.allowFrom "[\"%PHONE_NUMBER%\"]" >nul 2>&1
)
echo [OK] Phone whitelist set: %PHONE_NUMBER%

openclaw config set agents.defaults.workspace "%PROJECT_ROOT%\workspace" >nul 2>&1
echo [OK] Workspace set: %PROJECT_ROOT%\workspace

REM --- Step 5: Start everything ---
echo.
echo Step 5: Starting Synapse...
echo.

call "%PROJECT_ROOT%\synapse_start.bat"

echo.
echo ========================================
echo [OK] Onboarding complete!
echo ========================================
echo.
echo Next time, just run synapse_start.bat
echo.
pause
