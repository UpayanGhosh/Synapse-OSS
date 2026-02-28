#!/usr/bin/env pwsh
# Synapse Stop Script for Windows (PowerShell)

Write-Host ""
Write-Host "Stopping Synapse..."
Write-Host ""

# Stop API Gateway (port 8000)
Write-Host "Stopping API Gateway (port 8000)..."
$gateway = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($gateway) {
    $gateway | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Write-Host "   [OK] Stopped."
} else {
    Write-Host "   [--] Not running."
}

# Stop Ollama
Write-Host "Stopping Ollama..."
$ollama = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if ($ollama) {
    Stop-Process -Name "ollama" -Force -ErrorAction SilentlyContinue
    Write-Host "   [OK] Stopped."
} else {
    Write-Host "   [--] Not running."
}

# Stop OpenClaw Gateway (port 18789)
Write-Host "Stopping OpenClaw Gateway (port 18789)..."
$ocGateway = Get-NetTCPConnection -LocalPort 18789 -State Listen -ErrorAction SilentlyContinue
if ($ocGateway) {
    $ocGateway | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Write-Host "   [OK] Stopped."
} else {
    Write-Host "   [--] Not running."
}

Write-Host ""
Write-Host "Synapse stopped."
Write-Host ""
