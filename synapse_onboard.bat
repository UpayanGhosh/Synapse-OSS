@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM Synapse Onboard Script for Windows
REM Run this ONCE on first setup. For daily use, run synapse_start.bat instead.
REM
REM This script is a thin bootstrap launcher:
REM   1. Checks prerequisites (Python required; Ollama optional — for local models only)
REM   2. Creates .venv and installs dependencies
REM   3. Hands off to the Python wizard (synapse_cli.py onboard) which supports
REM      19 LLM providers incl. Gemini / Anthropic / OpenAI / Groq / OpenRouter /
REM      Mistral / xAI / Cohere / DeepSeek / Together AI, Chinese providers
REM      (MiniMax / Moonshot / Z.AI / Volcengine / Qianfan), self-hosted
REM      (Ollama / vLLM), and special providers (AWS Bedrock, Google Vertex AI,
REM      NVIDIA NIM, HuggingFace, GitHub Copilot OAuth).
REM   4. The wizard prefetches the embedding model (FastEmbed) and, if Ollama is
REM      selected, also pulls nomic-embed-text for offline fallback.
REM   5. Starts all services

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

REM Docker is NOT required — LanceDB vector store is embedded (no containers).

REM Ollama is OPTIONAL — enables local models (The Vault, privacy mode)
set "OLLAMA_EXE="
where ollama >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "OLLAMA_EXE=ollama"
) else if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
)

if defined OLLAMA_EXE (
    echo    [OK] Ollama ^(optional — enables local models^)
) else (
    echo    [--] Ollama: not installed ^(OPTIONAL^)
    echo         Ollama enables local models ^(The Vault, privacy mode^).
    echo         Skip if you don't need local models.
    echo         Install later from https://ollama.com if needed.
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
echo The wizard will ask which LLM provider(s) you want to use.
echo Supported: Gemini, Anthropic, OpenAI, Groq, OpenRouter, Mistral, xAI,
echo   Cohere, Together AI, DeepSeek, MiniMax, Moonshot, Z.AI, Volcengine,
echo   Qianfan, Ollama, vLLM, AWS Bedrock, Google Vertex AI, NVIDIA NIM,
echo   HuggingFace, and GitHub Copilot (OAuth device flow).
echo.
echo A new PowerShell window will open for the interactive wizard.
echo Complete the wizard there, then return to this window.
echo.
pause

REM Launch wizard in a new PowerShell window (requires proper ANSI terminal for
REM questionary checkbox/multiselect to register Space and arrow keypresses).
REM /wait makes this window block until the PowerShell window is closed.
REM Exit code is written to a temp file because `start /wait` loses ERRORLEVEL
REM when PowerShell exits — this is the only reliable way to capture it in cmd.

set "WIZARD_RESULT_FILE=%TEMP%\_synapse_wizard_result.txt"
echo 1 > "%WIZARD_RESULT_FILE%"

start /wait powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "& { $env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; & '%PROJECT_ROOT%\.venv\Scripts\python.exe' -X utf8 '%PROJECT_ROOT%\workspace\synapse_cli.py' onboard; Set-Content -Path '%WIZARD_RESULT_FILE%' -Value $LASTEXITCODE }"

set /p WIZARD_EXIT=<"%WIZARD_RESULT_FILE%"
set "WIZARD_EXIT=%WIZARD_EXIT: =%"

if "%WIZARD_EXIT%" NEQ "0" (
    echo.
    echo [X] Wizard exited with an error ^(code: %WIZARD_EXIT%^). Fix the issue and run this script again.
    echo.
    pause
    exit /b 1
)
echo    [OK] Wizard completed successfully.

REM ============================================================
REM Step 5: Start all services
REM ============================================================
echo.
echo Step 5: Starting services...
echo.

call "%PROJECT_ROOT%\synapse_start.bat"

REM ============================================================
REM Done
REM ============================================================
REM Note: Embedding model (FastEmbed nomic-embed-text-v1.5) is prefetched
REM by the Python wizard in Step 4. No separate download needed here.
echo.
echo ========================================
echo [OK] Onboarding complete!
echo ========================================
echo.
echo Next time, just run synapse_start.bat
echo.
pause
exit /b 0
