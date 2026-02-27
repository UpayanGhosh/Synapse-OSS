#!/usr/bin/env pwsh
#
# Synapse Start Script for Windows (PowerShell)
#
# This script starts all the necessary background services for Synapse to run.
# It assumes you have already run 'synapse_onboard.bat' at least once.

Write-Host "🚀 Starting Synapse services..."
Write-Host ""

$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$workspaceDir = Join-Path $projectRoot "workspace"

# Ensure OpenClaw workspace is configured and directories exist
$openclawWorkspace = "$HOME/.openclaw/workspace"
New-Item -Path (Join-Path $openclawWorkspace "db") -ItemType Directory -Force | Out-Null
New-Item -Path "$HOME/.openclaw/logs" -ItemType Directory -Force | Out-Null
openclaw config set workspaceDir $openclawWorkspace 2>$null

# 1. Start Docker Container
Write-Host -NoNewline "[1/4] Starting Qdrant..."
docker start antigravity_qdrant 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Started."
} else {
    Write-Host "✓ Already running or not found."
}

# 2. Start Ollama
Write-Host -NoNewline "[2/4] Starting Ollama..."
$ollama_process = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollama_process) {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Write-Host "✓ Started."
} else {
    Write-Host "✓ Already running."
}

# 3. Start API Gateway
Write-Host -NoNewline "[3/4] Starting API Gateway..."
$gateway_running = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
if (-not $gateway_running) {
    if (-not (Test-Path $venvPython)) {
         Write-Host "✗ ERROR: Could not find Python virtual environment. Cannot start gateway." -ForegroundColor Red
    } else {
        $uvicornArgs = "-m uvicorn sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000 --workers 1"
        Push-Location -Path $workspaceDir
        Start-Process -FilePath $venvPython -ArgumentList $uvicornArgs -WindowStyle Hidden
        Pop-Location
        Write-Host "✓ Started."
    }
} else {
    Write-Host "✓ Already running."
}

# 4. Start OpenClaw Gateway
Write-Host -NoNewline "[4/4] Starting OpenClaw Gateway..."
$oc_gateway_running = (Get-NetTCPConnection -LocalPort 18789 -State Listen -ErrorAction SilentlyContinue)
if (-not $oc_gateway_running) {
    Start-Process -FilePath "openclaw" -ArgumentList "gateway" -WindowStyle Hidden
    Write-Host "✓ Started."
} else {
    Write-Host "✓ Already running."
}

Write-Host ""
Write-Host "✅ Synapse is starting up. It may take a moment."
Write-Host "You can now message Synapse on WhatsApp."
