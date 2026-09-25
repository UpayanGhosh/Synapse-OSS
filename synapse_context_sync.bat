@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "PROJECT_ROOT=%~dp0"
set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

set "SYNC_STATE=%PROJECT_ROOT%\.tmp\context-sync"
set "UV_CACHE_DIR=%PROJECT_ROOT%\.tmp\uv-cache"
set "UV_TOOL_DIR=%PROJECT_ROOT%\.tmp\uv-tools"
set "UV_TOOL_BIN_DIR=%PROJECT_ROOT%\.tmp\uv-bin"
set "USERPROFILE=%SYNC_STATE%\profile"
set "LOCALAPPDATA=%SYNC_STATE%\localappdata"
set "MEMPALACE_CONFIG_DIR=%SYNC_STATE%\mempalace\config"
set "MEMPALACE_PALACE_PATH=%SYNC_STATE%\mempalace\palace"
set "TEMP=%SYNC_STATE%\tmp"
set "TMP=%TEMP%"
set "PYTHONPYCACHEPREFIX=%SYNC_STATE%\pycache"
if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%"
if not exist "%UV_TOOL_DIR%" mkdir "%UV_TOOL_DIR%"
if not exist "%UV_TOOL_BIN_DIR%" mkdir "%UV_TOOL_BIN_DIR%"
if not exist "%USERPROFILE%" mkdir "%USERPROFILE%"
if not exist "%LOCALAPPDATA%" mkdir "%LOCALAPPDATA%"
if not exist "%MEMPALACE_CONFIG_DIR%" mkdir "%MEMPALACE_CONFIG_DIR%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%PYTHONPYCACHEPREFIX%" mkdir "%PYTHONPYCACHEPREFIX%"

set "GRAPH_TOOL=code-review-graph@2.3.9"
set "MEMORY_TOOL=mempalace@3.10.0"
if not exist "%UV_TOOL_BIN_DIR%\code-review-graph.exe" (
    echo [ERROR] Pinned local tools missing. Install once with:
    echo         set UV_CACHE_DIR=%UV_CACHE_DIR%
    echo         set UV_TOOL_DIR=%UV_TOOL_DIR%
    echo         set UV_TOOL_BIN_DIR=%UV_TOOL_BIN_DIR%
    echo         uv tool install code-review-graph==2.3.9
    echo         uv tool install mempalace==3.10.0
    exit /b 1
)
if not exist "%UV_TOOL_BIN_DIR%\mempalace.exe" (
    echo [ERROR] Pinned MemPalace tool missing. Install once with:
    echo         uv tool install mempalace==3.10.0
    exit /b 1
)

echo [1/4] Updating code-review-graph...
uv tool run --offline %GRAPH_TOOL% update
if errorlevel 1 exit /b 1

echo [2/4] Graph status...
uv tool run --offline %GRAPH_TOOL% status
if errorlevel 1 exit /b 1

echo [3/4] Change risk snapshot...
uv tool run --offline %GRAPH_TOOL% detect-changes --base HEAD --brief
if errorlevel 1 exit /b 1

echo [4/4] Mining MemPalace...
if not exist "%MEMPALACE_PALACE_PATH%" (
    uv tool run --offline %MEMORY_TOOL% init . --yes --no-llm
    if errorlevel 1 exit /b 1
)
if "%SYNAPSE_CONTEXT_FULL_MINE%"=="1" (
    echo [INFO] Full project mine requested.
    uv tool run --offline %MEMORY_TOOL% mine .
    if errorlevel 1 exit /b 1
) else (
    if exist "%PROJECT_ROOT%\tasks" (
        echo [INFO] Mining tasks, up to 50 files...
        uv tool run --offline %MEMORY_TOOL% mine "%PROJECT_ROOT%\tasks" --limit 50
        if errorlevel 1 exit /b 1
    ) else (
        echo [INFO] Skipping missing tasks directory.
    )
    if exist "%PROJECT_ROOT%\docs\audits" (
        echo [INFO] Mining docs/audits, up to 50 files...
        uv tool run --offline %MEMORY_TOOL% mine "%PROJECT_ROOT%\docs\audits" --limit 50
        if errorlevel 1 exit /b 1
    ) else (
        echo [INFO] Skipping missing docs/audits directory.
    )
)

echo [OK] Context sync complete.
