@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM Synapse Onboard Script for Windows
REM Run this ONCE to configure Synapse, link WhatsApp, and start all services.

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

REM TODO Phase 7: openclaw binary check removed — system runs without openclaw
REM where openclaw >nul 2>&1
REM if %ERRORLEVEL% NEQ 0 (
REM     echo    [X] OpenClaw not installed. Install from https://github.com/openclaw/openclaw/releases
REM     set "MISSING=1"
REM ) else (
REM     echo    [OK] OpenClaw
REM )

where ollama >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    Ollama not found. Installing automatically...
    echo    Downloading installer (this may take a moment)...
    curl -L -o "%TEMP%\OllamaSetup.exe" "https://ollama.com/download/OllamaSetup.exe"
    if %ERRORLEVEL% NEQ 0 (
        echo    [X] Failed to download Ollama installer.
        echo        Install manually from https://ollama.com then run this script again.
        set "MISSING=1"
    ) else (
        echo    Running Ollama installer silently...
        "%TEMP%\OllamaSetup.exe" /S
        timeout /t 15 /nobreak >nul
        REM Refresh PATH in this session so ollama.exe is visible without restart
        for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "SYSTEM_PATH=%%B"
        set "PATH=%PATH%;%SYSTEM_PATH%"
        where ollama >nul 2>&1
        if %ERRORLEVEL% NEQ 0 (
            echo    [X] Ollama install did not complete. Install manually from https://ollama.com
            set "MISSING=1"
        ) else (
            echo    [OK] Ollama installed successfully
        )
    )
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

REM --- Step 2: .env setup ---
echo.
echo Step 2: Checking config...
echo.

if not exist "%PROJECT_ROOT%\.env" (
    if exist "%PROJECT_ROOT%\.env.example" (
        copy "%PROJECT_ROOT%\.env.example" "%PROJECT_ROOT%\.env" >nul
        echo [OK] Created .env from .env.example
    ) else (
        type nul > "%PROJECT_ROOT%\.env"
        echo [OK] Created empty .env
    )
)

REM --- Step 3: Link WhatsApp ---
echo.
echo Step 3: Linking WhatsApp...
echo.
echo WhatsApp link step deferred. Phase 4 will implement Baileys bridge QR code flow.
echo.

REM TODO Phase 4: WhatsApp login replaced by Baileys bridge QR code flow
REM openclaw channels login --channel whatsapp
REM if %ERRORLEVEL% NEQ 0 (
REM     echo.
REM     echo Note: openclaw channels login returned an error.
REM     echo This is normal if WhatsApp is already linked. Continuing...
REM     echo.
REM )
echo [OK] WhatsApp step noted (deferred to Phase 4).

REM --- Step 4: Phone number ---
echo.
echo Step 4: Your phone number...
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

REM --- Step 5: Configure Synapse ---
echo.
echo Step 5: Saving config...
echo.

REM TODO Phase 4: phone allowlist moved to synapse.json
REM openclaw config set channels.whatsapp.allowFrom "[\"%PHONE_NUMBER%\"]" --json >nul 2>&1
REM if %ERRORLEVEL% NEQ 0 (
REM     openclaw config set channels.whatsapp.allowFrom "[\"%PHONE_NUMBER%\"]" >nul 2>&1
REM )
echo [OK] Phone number noted: %PHONE_NUMBER%
echo     Configure in %%USERPROFILE%%\.synapse\synapse.json once Phase 4 Baileys bridge is installed.

REM TODO Phase 1: workspace path now read from SYNAPSE_HOME / SynapseConfig
REM openclaw config set agents.defaults.workspace "%PROJECT_ROOT%\workspace" >nul 2>&1
echo [OK] Workspace: %PROJECT_ROOT%\workspace (read from SynapseConfig)

REM --- Step 6: Configure LLM access ---
echo.
echo Step 6: Configuring LLM access...
echo.

REM TODO Phase 2: provider token moved to synapse.json
REM set "GW_TOKEN="
REM for /f "tokens=*" %%T in ('openclaw config get gateway.auth.token 2^>nul') do set "GW_TOKEN=%%T"
REM if defined GW_TOKEN (
REM     ...openclaw gateway token block removed...
REM )

REM Check for direct Gemini key
findstr /B /C:"GEMINI_API_KEY=" "%PROJECT_ROOT%\.env" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] GEMINI_API_KEY found in .env -- Synapse will call Gemini directly
) else (
    echo.
    echo WARNING: No LLM configured. Synapse will start but replies will fail.
    echo    Fix: add to .env --
    echo       GEMINI_API_KEY=your_key        (free at aistudio.google.com)
    echo.
)

:llm_done

REM --- Step 7: Start everything ---
echo.
echo Step 7: Starting Synapse...
echo.

call "%PROJECT_ROOT%\synapse_start.bat"

REM Pull the required embedding model synchronously so it is ready before first use
echo.
echo Pulling required embedding model (nomic-embed-text)...
echo This downloads ~900 MB on first run. Please wait...
ollama pull nomic-embed-text
echo [OK] nomic-embed-text ready

echo.
echo ========================================
echo [OK] Onboarding complete!
echo ========================================
echo.
echo Next time, just run synapse_start.bat
echo.
pause
