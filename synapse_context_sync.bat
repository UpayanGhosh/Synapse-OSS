@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

echo [1/4] Updating code-review-graph...
uv tool run --offline code-review-graph update
if errorlevel 1 exit /b %errorlevel%

echo [2/4] Graph status...
uv tool run --offline code-review-graph status
if errorlevel 1 exit /b %errorlevel%

echo [3/4] Change risk snapshot...
uv tool run --offline code-review-graph detect-changes --base HEAD --brief
if errorlevel 1 exit /b %errorlevel%

echo [4/4] Mining MemPalace...
if not exist "%PROJECT_ROOT%\mempalace.yaml" (
    mempalace init . --yes
    if errorlevel 1 exit /b %errorlevel%
)
mempalace mine .
if errorlevel 1 exit /b %errorlevel%

echo [OK] Context sync complete.
