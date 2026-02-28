@echo off
chcp 65001 >nul
setlocal

echo.
echo Stopping Synapse...
echo.

REM --- Stop API Gateway (port 8000) ---
echo Stopping API Gateway...
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1 && echo    [OK] Stopped process on port 8000.
)

REM --- Stop Ollama ---
echo Stopping Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if %ERRORLEVEL% EQU 0 (
    taskkill /IM ollama.exe /F >nul 2>&1
    echo    [OK] Ollama stopped.
) else (
    echo    [--] Ollama was not running.
)

REM --- Stop OpenClaw Gateway (port 18789) ---
echo Stopping OpenClaw Gateway...
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":18789" ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1 && echo    [OK] Stopped process on port 18789.
)

echo.
echo Synapse stopped.
echo.
pause
