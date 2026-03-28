@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM Synapse Onboard Script for Windows
REM Run this ONCE to configure Synapse, link WhatsApp, and start all services.

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "SYNAPSE_HOME=%USERPROFILE%\.synapse"
set "SYNAPSE_CONFIG=%SYNAPSE_HOME%\synapse.json"

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

REM --- Step 2: Local config setup ---
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

if not exist "%SYNAPSE_HOME%" (
    mkdir "%SYNAPSE_HOME%" >nul 2>&1
)

if not exist "%SYNAPSE_CONFIG%" (
    if exist "%PROJECT_ROOT%\synapse.json.example" (
        copy "%PROJECT_ROOT%\synapse.json.example" "%SYNAPSE_CONFIG%" >nul
        echo [OK] Created synapse.json from synapse.json.example
    ) else (
        echo {>"%SYNAPSE_CONFIG%"
        echo   "providers": {},>>"%SYNAPSE_CONFIG%"
        echo   "channels": {},>>"%SYNAPSE_CONFIG%"
        echo   "model_mappings": {}>>"%SYNAPSE_CONFIG%"
        echo }>>"%SYNAPSE_CONFIG%"
        echo [OK] Created empty synapse.json
    )
)

echo [OK] Synapse config home: %SYNAPSE_HOME%

REM --- Step 3: Choose messaging channels ---
echo.
echo Step 3: Choosing messaging channels...
echo.
echo Select the messaging channels you want to configure now.
echo You can choose more than one.
echo.
echo   1. WhatsApp
echo   2. Telegram
echo   3. Discord
echo   4. Slack
echo.

:channel_select
set "CHANNEL_WHATSAPP=0"
set "CHANNEL_TELEGRAM=0"
set "CHANNEL_DISCORD=0"
set "CHANNEL_SLACK=0"
set "INVALID_CHANNEL="
set "CHANNEL_CHOICES="
set /p CHANNEL_CHOICES="Enter one or more numbers separated by commas: "

for %%C in (%CHANNEL_CHOICES:,= %) do (
    if "%%C"=="1" (
        set "CHANNEL_WHATSAPP=1"
    ) else if "%%C"=="2" (
        set "CHANNEL_TELEGRAM=1"
    ) else if "%%C"=="3" (
        set "CHANNEL_DISCORD=1"
    ) else if "%%C"=="4" (
        set "CHANNEL_SLACK=1"
    ) else (
        set "INVALID_CHANNEL=1"
    )
)

if defined INVALID_CHANNEL (
    echo.
    echo Invalid selection. Choose any of: 1, 2, 3, 4
    echo.
    goto channel_select
)

if "%CHANNEL_WHATSAPP%%CHANNEL_TELEGRAM%%CHANNEL_DISCORD%%CHANNEL_SLACK%"=="0000" (
    echo.
    echo Choose at least one messaging channel.
    echo.
    goto channel_select
)

echo.
echo [OK] Channel selection captured.

REM --- Step 4: Channel-specific setup ---
echo.
echo Step 4: Configuring selected channels...
echo.

set "PHONE_NUMBER="
set "TELEGRAM_TOKEN="
set "DISCORD_TOKEN="
set "DISCORD_CHANNEL_IDS="
set "SLACK_BOT_TOKEN="
set "SLACK_APP_TOKEN="

if "%CHANNEL_WHATSAPP%"=="1" (
    echo WhatsApp selected.
    echo Synapse will start the Baileys bridge after onboarding.
    echo After startup, open http://localhost:8000/qr to get the pairing QR code.
    echo Scan it in WhatsApp ^> Settings ^> Linked Devices ^> Link a Device.
    echo.
    echo Synapse uses your phone number to identify you on WhatsApp.
    echo Enter your number with country code, for example +15551234567
    echo.
    call :capture_whatsapp_phone
    echo [OK] WhatsApp number noted: !PHONE_NUMBER!
    echo.
)

if "%CHANNEL_TELEGRAM%"=="1" (
    echo Telegram selected.
    echo Create a bot with @BotFather and paste the bot token below.
    set /p TELEGRAM_TOKEN="Telegram bot token ^(leave blank to skip^): "
    if defined TELEGRAM_TOKEN (
        echo [OK] Telegram token captured.
    ) else (
        echo [--] Telegram skipped.
    )
    echo.
)

if "%CHANNEL_DISCORD%"=="1" (
    echo Discord selected.
    echo Create a bot in the Discord Developer Portal and paste the bot token below.
    set /p DISCORD_TOKEN="Discord bot token ^(leave blank to skip^): "
    if defined DISCORD_TOKEN (
        echo Enable MESSAGE CONTENT INTENT in the Discord Developer Portal before using the bot.
        set /p DISCORD_CHANNEL_IDS="Allowed Discord channel IDs ^(comma-separated, blank means all^): "
        echo [OK] Discord token captured.
    ) else (
        echo [--] Discord skipped.
    )
    echo.
)

if "%CHANNEL_SLACK%"=="1" (
    echo Slack selected.
    echo You need both a bot token and an app token.
    echo Bot token location: Slack App ^> OAuth and Permissions ^> Bot User OAuth Token
    echo App token location: Slack App ^> Basic Information ^> App-Level Tokens
    echo The app token must have the connections:write scope.
    set /p SLACK_BOT_TOKEN="Slack bot token ^(xoxb-..., leave blank to skip^): "
    if defined SLACK_BOT_TOKEN (
        set /p SLACK_APP_TOKEN="Slack app token ^(xapp-...^): "
        if defined SLACK_APP_TOKEN (
            echo [OK] Slack tokens captured.
        ) else (
            set "SLACK_BOT_TOKEN="
            echo [--] Slack skipped because the app token was blank.
        )
    ) else (
        echo [--] Slack skipped.
    )
    echo.
)

REM --- Step 5: Save channel config ---
echo.
echo Step 5: Saving channel config...
echo.

set "CFG_WHATSAPP=%CHANNEL_WHATSAPP%"
set "CFG_PHONE_NUMBER=%PHONE_NUMBER%"
set "CFG_TELEGRAM_TOKEN=%TELEGRAM_TOKEN%"
set "CFG_DISCORD_TOKEN=%DISCORD_TOKEN%"
set "CFG_DISCORD_CHANNEL_IDS=%DISCORD_CHANNEL_IDS%"
set "CFG_SLACK_BOT_TOKEN=%SLACK_BOT_TOKEN%"
set "CFG_SLACK_APP_TOKEN=%SLACK_APP_TOKEN%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$cfgPath = Join-Path $env:USERPROFILE '.synapse\synapse.json';" ^
  "$cfgDir = Split-Path -Parent $cfgPath;" ^
  "New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null;" ^
  "if (Test-Path $cfgPath) { $cfg = Get-Content -Raw $cfgPath | ConvertFrom-Json } else { $cfg = [pscustomobject]@{} };" ^
  "if ($null -eq $cfg) { $cfg = [pscustomobject]@{} };" ^
  "if (-not ($cfg.PSObject.Properties.Name -contains 'providers')) { $cfg | Add-Member -NotePropertyName providers -NotePropertyValue ([ordered]@{}) };" ^
  "if (-not ($cfg.PSObject.Properties.Name -contains 'model_mappings')) { $cfg | Add-Member -NotePropertyName model_mappings -NotePropertyValue ([ordered]@{}) };" ^
  "if (-not ($cfg.PSObject.Properties.Name -contains 'channels')) { $cfg | Add-Member -NotePropertyName channels -NotePropertyValue ([ordered]@{}) };" ^
  "$channels = [ordered]@{};" ^
  "if ($env:CFG_WHATSAPP -eq '1') { $channels['whatsapp'] = [ordered]@{ enabled = $true; bridge_port = 5010; admin_phone = $env:CFG_PHONE_NUMBER } };" ^
  "if (-not [string]::IsNullOrWhiteSpace($env:CFG_TELEGRAM_TOKEN)) { $channels['telegram'] = [ordered]@{ token = $env:CFG_TELEGRAM_TOKEN } };" ^
  "if (-not [string]::IsNullOrWhiteSpace($env:CFG_DISCORD_TOKEN)) { $allowed = @(); if (-not [string]::IsNullOrWhiteSpace($env:CFG_DISCORD_CHANNEL_IDS)) { $allowed = @($env:CFG_DISCORD_CHANNEL_IDS.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int64]$_ }) }; $channels['discord'] = [ordered]@{ token = $env:CFG_DISCORD_TOKEN; allowed_channel_ids = $allowed } };" ^
  "if (-not [string]::IsNullOrWhiteSpace($env:CFG_SLACK_BOT_TOKEN) -and -not [string]::IsNullOrWhiteSpace($env:CFG_SLACK_APP_TOKEN)) { $channels['slack'] = [ordered]@{ bot_token = $env:CFG_SLACK_BOT_TOKEN; app_token = $env:CFG_SLACK_APP_TOKEN } };" ^
  "$cfg.channels = $channels;" ^
  "$cfg | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $cfgPath"

if %ERRORLEVEL% NEQ 0 (
    echo [X] Failed to write %SYNAPSE_CONFIG%
    pause
    exit /b 1
)

if defined PHONE_NUMBER (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$envPath = '%PROJECT_ROOT%\.env';" ^
      "$phone = $env:CFG_PHONE_NUMBER;" ^
      "$lines = if (Test-Path $envPath) { @(Get-Content $envPath) } else { @() };" ^
      "$updated = $false;" ^
      "for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^ADMIN_PHONE=') { $lines[$i] = ('ADMIN_PHONE=\"' + $phone + '\"'); $updated = $true } };" ^
      "if (-not $updated) { $lines += ('ADMIN_PHONE=\"' + $phone + '\"') };" ^
      "Set-Content -Encoding UTF8 $envPath $lines"
)

echo [OK] Saved channel settings to %SYNAPSE_CONFIG%
echo [OK] Workspace: %PROJECT_ROOT%\workspace

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
    echo       GEMINI_API_KEY=your_key        ^(free at aistudio.google.com^)
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
echo Channel next steps:
if "%CHANNEL_WHATSAPP%"=="1" (
    echo    WhatsApp: open http://localhost:8000/qr and scan the QR code in Linked Devices.
)
if defined TELEGRAM_TOKEN (
    echo    Telegram: open your bot in Telegram and send it a message.
)
if defined DISCORD_TOKEN (
    echo    Discord: invite the bot to your server, enable MESSAGE CONTENT INTENT, then mention it.
)
if defined SLACK_BOT_TOKEN if defined SLACK_APP_TOKEN (
    echo    Slack: install the app to your workspace and add it to the channel you want to use.
)

echo.
echo ========================================
echo [OK] Onboarding complete!
echo ========================================
echo.
echo Next time, just run synapse_start.bat
echo.
pause
exit /b 0

:capture_whatsapp_phone
set "PHONE_NUMBER="
:phone_input_loop
set /p PHONE_NUMBER="Your WhatsApp number: "
powershell -Command "if ('!PHONE_NUMBER!' -match '^\+[0-9]{10,15}$') { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Invalid format. Use E.164 format starting with + and country code.
    echo   India: +919836939194   US: +15551234567   UK: +447912345678
    echo.
    goto phone_input_loop
)
exit /b 0
