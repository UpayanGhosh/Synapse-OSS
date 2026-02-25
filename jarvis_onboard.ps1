#!/usr/bin/env pwsh
#
# Jarvis Onboard Script for Windows (PowerShell)
#
# This script guides a user through the initial setup and launch of Jarvis.
# It is designed to be run in a PowerShell terminal on Windows.

Write-Host ""
Write-Host "🤖 ======================================="
Write-Host "   Jarvis Onboard - Let's Get Started!"
Write-Host "=========================================="
Write-Host ""

Write-Host "Hi there! I'm going to guide you through setting up Jarvis on Windows."
Write-Host "This will only take a few minutes."
Write-Host ""

Read-Host -Prompt "Press Enter to continue..."

# Section 1: Pre-flight checks
#--------------------------------------------------------------------------
Write-Host ""
Write-Host "🔍 Step 1: Checking your tools..."
Write-Host ""

function Check-Tool {
    param($toolName)
    if (Get-Command $toolName -ErrorAction SilentlyContinue) {
        Write-Host "   ✓ $toolName is installed"
        return $true
    } else {
        Write-Host "   ✗ $toolName is NOT installed"
        return $false
    }
}

$all_good = $true

if (-not (Check-Tool "git")) { $all_good = $false }
# On Windows, Python is often just 'python' and not 'python3'
if (-not (Check-Tool "python")) {
    if (-not (Check-Tool "python3")) {
        Write-Host "   (Also checked for 'python3', which was not found.)"
        $all_good = $false
    }
}
if (-not (Check-Tool "docker")) { $all_good = $false }
if (-not (Check-Tool "openclaw")) { $all_good = $false }

if (-not $all_good) {
    Write-Host ""
    Write-Host "❌ Oops! Some tools are missing."
    Write-Host ""
    Write-Host "Please install the missing tools from the links in HOW_TO_RUN.md and try again."
    Write-Host ""
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}

# Explicitly check if Docker Desktop is running, a common issue on Windows.
Write-Host -n "   - Docker Desktop Status: "
try {
    docker info > $null
    Write-Host "✓ Running"
}
catch {
    Write-Host "✗ Not responding" -ForegroundColor Red
    Write-Host ""
    Write-Host "Error: The Docker daemon isn't running. Please start Docker Desktop and wait for it"
    Write-Host "to be fully initialized, then run this script again."
    Write-Host ""
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "✅ All tools are ready!"
Write-Host ""

Read-Host -Prompt "Press Enter to continue to WhatsApp setup..."


# Section 2: WhatsApp Setup
#--------------------------------------------------------------------------
Write-Host ""
Write-Host "📱 ======================================="
Write-Host "   Step 2: Connect Your WhatsApp"
Write-Host "=========================================="
Write-Host ""
Write-Host "Here's an important question:"
Write-Host ""

while ($true) {
    Write-Host "Do you want to use:"
    Write-Host ""
    Write-Host "   [1] Dedicated Number (recommended)"
    Write-Host "       Use a separate phone number just for Jarvis"
    Write-Host "       (like an old Android phone or spare SIM)"
    Write-Host ""
    Write-Host "   [2] Personal Number"
    Write-Host "       Use your own WhatsApp number"
    Write-Host "       You'll chat with Jarvis by 'messaging yourself'"
    Write-Host ""
    $choice = Read-Host -Prompt "Enter 1 or 2"

    if ($choice -eq "1") {
        $phone_type = "dedicated"
        Write-Host ""
        Write-Host "✓ Great choice!"
        Write-Host ""
        Write-Host "With a dedicated number, your personal WhatsApp stays private."
        Write-Host "Just use an old phone or spare SIM card."
        break
    }
    if ($choice -eq "2") {
        $phone_type = "personal"
        Write-Host ""
        Write-Host "✓ No problem!"
        Write-Host ""
        Write-Host "You'll find Jarvis in your 'Message yourself' chat."
        Write-Host "It's like texting yourself!"
        break
    }
    Write-Host "Please enter 1 or 2"
    Write-Host ""
}

Write-Host ""
Write-Host "Now let's link your WhatsApp..."
Write-Host ""
Write-Host "⚠️  A QR code will appear on your screen!" -ForegroundColor Yellow
Write-Host ""
Write-Host "   1. Open WhatsApp on your phone"
Write-Host "   2. Go to Settings → Linked Devices"
Write-Host "   3. Tap 'Link a Device'"
Write-Host "   4. Scan the QR code below"
Write-Host ""

Read-Host -Prompt "Press Enter to show the QR code..."

Write-Host ""
Write-Host "Scan the QR code now! I'll wait..."
Write-Host ""

openclaw channels login

Write-Host ""
Write-Host "✓ WhatsApp linked!"
Write-Host ""

Read-Host -Prompt "Press Enter to continue..."

Write-Host ""
Write-Host "📞 Enter your phone number..."
Write-Host ""
Write-Host "This lets Jarvis know it's YOU messaging it."
Write-Host "Enter your number with country code (e.g., +15551234567)"
Write-Host ""

while ($true) {
    $phone_number = Read-Host -Prompt "Your phone number"
    if ([string]::IsNullOrWhiteSpace($phone_number)) {
        Write-Host "Phone number cannot be empty. Please try again."
        continue
    }
    if ($phone_number -notmatch '^\+[0-9]{10,15}$') {
        Write-Host "Invalid format! Use E.164 format like:"
        Write-Host "   • US: +15551234567"
        Write-Host "   • India: +919876543210"
        Write-Host "   • UK: +447912345678"
        Write-Host "(Start with +, include country code, 10-15 digits total)"
        continue
    }
    break
}

Write-Host ""
Write-Host "Saving phone number to OpenClaw config..."
Write-Host ""

openclaw config set channels.whatsapp.allowFrom "["$phone_number"]" --json 2>$null
if ($LASTEXITCODE -ne 0) {
    openclaw config set channels.whatsapp.allowFrom "["$phone_number"]"
}

Write-Host "✓ Phone number saved: $phone_number"
Write-Host ""

# Section 3: Start Services
#--------------------------------------------------------------------------
Write-Host ""
Write-Host "🚀 ======================================="
Write-Host "   Step 3: Starting All Jarvis Services"
Write-Host "=========================================="
Write-Host ""
Write-Host "Starting all services in the background..."
Write-Host ""

# Ensure log directory exists
$logDir = "$HOME/.openclaw/logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory -Force | Out-Null
}

# 1. Qdrant
Write-Host "[1/4] Starting Docker services (Qdrant)..."
docker start antigravity_qdrant 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✓ Qdrant started"
} else {
    Write-Host "   ⚠ Qdrant not found or already running (optional)."
}

# 2. Ollama
Write-Host ""
Write-Host "[2/4] Starting Ollama..."
$ollama_process = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollama_process) {
    # Start-Process is the PowerShell equivalent of nohup ... &
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Write-Host "   ✓ Ollama started in background."
} else {
    Write-Host "   ✓ Ollama already running."
}

# 3. API Gateway
Write-Host ""
Write-Host "[3/4] Starting API Gateway..."
$gateway_running = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
if (-not $gateway_running) {
    # Run python from the virtual environment.
    $projectRoot = $PSScriptRoot
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

    if (-not (Test-Path $venvPython)) {
        Write-Host "   ✗ ERROR: Could not find Python in the virtual environment at:" -ForegroundColor Red
        Write-Host "     $venvPython"
        Write-Host "   Please ensure you have run 'python -m venv .venv' and 'pip install -r requirements.txt'"
        Read-Host -Prompt "Press Enter to exit"
        exit 1
    }
    
    # Run uvicorn as a module from the workspace directory
    $uvicornArgs = "-m uvicorn sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000 --workers 1"
    $workspaceDir = Join-Path $projectRoot "workspace"

    Push-Location -Path $workspaceDir
    Start-Process -FilePath $venvPython -ArgumentList $uvicornArgs -WindowStyle Hidden
    Pop-Location

    Write-Host "   ✓ API Gateway started in background."
} else {
    Write-Host "   ✓ API Gateway appears to be already running (port 8000 is active)."
}

# 4. OpenClaw Gateway
Write-Host ""
Write-Host "[4/4] Starting OpenClaw Gateway (WhatsApp bridge)..."
$oc_gateway_running = (Get-NetTCPConnection -LocalPort 18789 -State Listen -ErrorAction SilentlyContinue)
if (-not $oc_gateway_running) {
    Start-Process -FilePath "openclaw" -ArgumentList "gateway" -WindowStyle Hidden
    Write-Host "   ✓ OpenClaw Gateway started in background."
} else {
    Write-Host "   ✓ OpenClaw Gateway appears to be already running (port 18789 is active)."
}

# Section 4: Verification
#--------------------------------------------------------------------------
Write-Host ""
Write-Host "⏳ Waiting for services to initialize..."
Start-Sleep -Seconds 10 # Give a bit more time for Windows systems

Write-Host ""
Write-Host "🔍 Verifying services..."
Write-Host ""

$services_ok = $true

# Health check for API Gateway
Write-Host -n "   - API Gateway (port 8000): "
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "✓ Running"
}
catch {
    try {
        # Fallback for servers that don't have /health but are running
        Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        Write-Host "✓ Running (Responded from root)"
    }
    catch {
        Write-Host "⚠ No response" -ForegroundColor Yellow
        $services_ok = $false
    }
}

# Health check for OpenClaw Gateway
Write-Host -n "   - OpenClaw Gateway: "
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:18789/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "✓ Running"
}
catch {
    Write-Host "⚠ No response" -ForegroundColor Yellow
    $services_ok = $false
}


if ($services_ok) {
    Write-Host ""
    Write-Host "✅ All essential services are running!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "⚠️  Some services may not have started correctly. Check logs or try running 'jarvis_start.ps1'." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "✓ Jarvis is running!"
Write-Host ""

# Final instructions
#--------------------------------------------------------------------------
Write-Host ""
Write-Host "💬 ======================================="
Write-Host "   Step 4: How to Chat with Jarvis"
Write-Host "=========================================="
Write-Host ""

if ($phone_type -eq "dedicated") {
    Write-Host "🎉 You're all set!"
    Write-Host ""
    Write-Host "To chat with Jarvis:"
    Write-Host "   1. Open WhatsApp on your phone"
    Write-Host "   2. Find 'Jarvis' or 'WhatsApp Web' in your contacts"
    Write-Host "   3. Send a message!"
} else {
    Write-Host "🎉 You're all set!"
    Write-Host ""
    Write-Host "To chat with Jarvis:"
    Write-Host "   1. Open WhatsApp on your phone"
    Write-Host "   2. Go to your chat list"
    Write-Host "   3. Tap on 'Message yourself' (your name at the top)"
    Write-Host "   4. Send a message to yourself!"
    Write-Host ""
    Write-Host "   Don't see 'Message yourself'?"
    Write-Host "   - Tap the pencil icon in your chat list"
    Write-Host "   - Your name should be at the top"
}

Write-Host ""
Write-Host "=========================================="
Write-Host "   🎉 You're Ready!"
Write-Host "=========================================="
Write-Host ""
Write-Host "Try sending:"
Write-Host "   • 'Hello'"
Write-Host "   • 'What's the weather?'"
Write-Host "   • 'Tell me a joke'"
Write-Host ""
Write-Host "Jarvis will reply! Have fun! 🤖"
Write-Host ""
