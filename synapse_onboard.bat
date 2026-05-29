@echo off
chcp 65001 >nul
setlocal

where synapse >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Synapse CLI not found.
    echo Install first: npm install -g synapse-oss
    exit /b 1
)

synapse install
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

synapse onboard
exit /b %ERRORLEVEL%
