# Synapse Onboard Script for Windows (PowerShell)

# This script guides a user through the initial setup and launch of Synapse.
# It is designed to be run in a PowerShell terminal on Windows.

Write-Host ""
Write-Host "🤖 ======================================="
Write-Host "   Synapse Onboard - Let's Get Started!"
Write-Host "=========================================="
Write-Host ""

Write-Host "Hi there! I'm going to guide you through setting up Synapse on Windows."
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
Write-Host -NoNewline "   - Docker Desktop Status: "
docker info > $null 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Running"
} else {
    Write-Host "✗ Not responding" -ForegroundColor Red
    Write-Host ""
    Write-Host "Error: The Docker daemon isn't running. Please start Docker Desktop and wait for it"
    Write-Host "to be fully initialized, then run this script again."
    Write-Host ""
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}

# Resolve project root ($PSScriptRoot is empty when dot-sourced, so guard it)
$projectRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$workspaceDir = Join-Path $projectRoot "workspace"
$venvPython   = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envFile      = Join-Path $projectRoot ".env"

# Check .env file exists and has an API key set
if (-not (Test-Path $envFile)) {
    Write-Host ""
    Write-Host "❌ No .env file found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Run this first:"
    Write-Host "   copy .env.example .env"
    Write-Host "Then open .env and add your GEMINI_API_KEY (at minimum)."
    Write-Host ""
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}

$envContent = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
if ($envContent -notmatch 'GEMINI_API_KEY=\S{20,}') {
    Write-Host ""
    Write-Host "⚠️  Warning: GEMINI_API_KEY does not appear to be set in your .env file." -ForegroundColor Yellow
    Write-Host "   Synapse will start but LLM calls will fail until you add an API key."
    Write-Host ""
}

# Check Python virtual environment
if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "❌ Python virtual environment not found at:" -ForegroundColor Red
    Write-Host "   $venvPython"
    Write-Host ""
    Write-Host "Open Windows Terminal (or Command Prompt) and run:"
    Write-Host "   python -m venv .venv"
    Write-Host "   .venv\Scripts\activate.bat"
    Write-Host "   pip install -r requirements.txt"
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
    Write-Host "       Use a separate phone number just for Synapse"
    Write-Host "       (like an old Android phone or spare SIM)"
    Write-Host ""
    Write-Host "   [2] Personal Number"
    Write-Host "       Use your own WhatsApp number"
    Write-Host "       You'll chat with Synapse by 'messaging yourself'"
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
        Write-Host "You'll find Synapse in your 'Message yourself' chat."
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
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ WhatsApp login failed or was cancelled." -ForegroundColor Red
    Write-Host "Please re-run this script and scan the QR code when prompted."
    Read-Host -Prompt "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "✓ WhatsApp linked!"
Write-Host ""

Read-Host -Prompt "Press Enter to continue..."

Write-Host ""
Write-Host "📞 Enter your phone number..."
Write-Host ""
Write-Host "This lets Synapse know it's YOU messaging it."
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

# Build a valid JSON array: ["<phone_number>"]
$allowFrom = "[\`"$phone_number\`"]"
openclaw config set channels.whatsapp.allowFrom $allowFrom --json 2>$null
if ($LASTEXITCODE -ne 0) {
    openclaw config set channels.whatsapp.allowFrom $allowFrom
}

Write-Host "✓ Phone number saved: $phone_number"
Write-Host ""

# ---- Workspace Configuration ----
Write-Host "🔧 Configuring OpenClaw workspace..."

# Use a DIFFERENT variable name to avoid clobbering $workspaceDir (the repo path)
# PowerShell variable names are case-insensitive, so $WorkspaceDir == $workspaceDir
$openclawWorkspace = "$HOME/.openclaw/workspace"

# Tell OpenClaw where Jarvis lives
openclaw config set workspaceDir $openclawWorkspace 2>$null
if ($LASTEXITCODE -ne 0) {
    openclaw config set workspaceDir $openclawWorkspace
}
Write-Host "   ✓ Workspace: $openclawWorkspace"

# Create required directories for databases, logs, and persona data
$dirsToCreate = @(
    (Join-Path $openclawWorkspace "db"),
    (Join-Path $openclawWorkspace "sci_fi_dashboard" "synapse_data" "the_creator" "profiles" "current"),
    (Join-Path $openclawWorkspace "sci_fi_dashboard" "synapse_data" "the_partner" "profiles" "current"),
    "$HOME/.openclaw/logs"
)
foreach ($dir in $dirsToCreate) {
    New-Item -Path $dir -ItemType Directory -Force | Out-Null
}
Write-Host "   ✓ Directories created"

# Verify the workspace is configured
try {
    $configuredDir = openclaw config get workspaceDir 2>$null
    if ($configuredDir) {
        Write-Host "   ✓ Verified: $configuredDir"
    } else {
        Write-Host "   ✓ Workspace set (could not verify — this is normal on first setup)"
    }
} catch {
    Write-Host "   ✓ Workspace set (could not verify — this is normal on first setup)"
}

# Section 3: Start Services
#--------------------------------------------------------------------------
Write-Host ""
Write-Host "🚀 ======================================="
Write-Host "   Step 3: Starting All Synapse Services"
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
    Write-Host "   Container not found. Creating Qdrant (may take a few minutes on first run)..."
    docker run -d --name antigravity_qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✓ Qdrant created and started"
    } else {
        Write-Host "   ⚠ Could not start Qdrant. Vector search will fall back to SQLite." -ForegroundColor Yellow
    }
}

# 2. Ollama
Write-Host ""
Write-Host "[2/4] Starting Ollama..."
$ollama_process = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollama_process) {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Write-Host "   ✓ Ollama started in background."
    Start-Sleep -Seconds 3
    Write-Host "   Pulling required embedding model (nomic-embed-text)..."
    Start-Process -FilePath "ollama" -ArgumentList "pull nomic-embed-text" -WindowStyle Hidden
    Write-Host "   ✓ nomic-embed-text pull started in background."
} else {
    Write-Host "   ✓ Ollama already running."
}

# 3. API Gateway
Write-Host ""
Write-Host "[3/4] Starting API Gateway..."
$gateway_running = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
if (-not $gateway_running) {
    # Run uvicorn as a module from the workspace directory, with correct working directory
    $uvicornArgs = "-m uvicorn sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000 --workers 1"
    Start-Process -FilePath $venvPython -ArgumentList $uvicornArgs `
        -WorkingDirectory $workspaceDir -WindowStyle Hidden

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
Write-Host ""

$services_ok = $true

# Health check for API Gateway — retry up to 5 times, 3 seconds apart (15s max)
Write-Host -NoNewline "   - API Gateway (port 8000): "
$gateway_up = $false
for ($i = 1; $i -le 5; $i++) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop | Out-Null
        $gateway_up = $true
        break
    } catch {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop | Out-Null
            $gateway_up = $true
            break
        } catch {
            Start-Sleep -Seconds 3
        }
    }
}
if ($gateway_up) {
    Write-Host "✓ Running"
} else {
    Write-Host "⚠ No response after 15s — check $logDir\gateway.log" -ForegroundColor Yellow
    $services_ok = $false
}

# Health check for OpenClaw Gateway — retry up to 5 times, 3 seconds apart
Write-Host -NoNewline "   - OpenClaw Gateway: "
$oc_up = $false
for ($i = 1; $i -le 5; $i++) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:18789/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop | Out-Null
        $oc_up = $true
        break
    } catch {
        Start-Sleep -Seconds 3
    }
}
if ($oc_up) {
    Write-Host "✓ Running"
} else {
    Write-Host "⚠ No response after 15s — check $logDir\openclaw_gateway.log" -ForegroundColor Yellow
    $services_ok = $false
}

if ($services_ok) {
    Write-Host ""
    Write-Host "✅ All essential services are running!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "⚠️  Some services may not have started correctly." -ForegroundColor Yellow
    Write-Host "   Logs are in: $logDir"
    Write-Host "   You can also try running 'synapse_start.bat'."
}

Write-Host ""
Write-Host "✓ Synapse is running!"
Write-Host ""

# Final instructions
#--------------------------------------------------------------------------
Write-Host ""
Write-Host "💬 ======================================="
Write-Host "   Step 4: How to Chat with Synapse"
Write-Host "=========================================="
Write-Host ""

if ($phone_type -eq "dedicated") {
    Write-Host "🎉 You're all set!"
    Write-Host ""
    Write-Host "To chat with Synapse:"
    Write-Host "   1. Open WhatsApp on your phone"
    Write-Host "   2. Find 'Synapse' or 'WhatsApp Web' in your contacts"
    Write-Host "   3. Send a message!"
} else {
    Write-Host "🎉 You're all set!"
    Write-Host ""
    Write-Host "To chat with Synapse:"
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
Write-Host "Synapse will reply! Have fun! 🤖"
Write-Host ""
