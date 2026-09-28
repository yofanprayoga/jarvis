# Automated deployment script for target living-room laptop
# Run in PowerShell: .\scripts\setup_target.ps1

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Jarvis-lite Deployment Script for Target Laptop" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check Python
Write-Host "`n[1/5] Checking Python 3.11+..." -ForegroundColor Yellow
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python not found. Installing Python 3.11 via winget..." -ForegroundColor Yellow
    winget install Python.Python.3.11 --scope user --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "Python found: $($py.Source)" -ForegroundColor Green
}

# 2. Virtual Environment
Write-Host "`n[2/5] Setting up virtual environment (.venv)..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Check / Install Ollama
Write-Host "`n[3/5] Checking Ollama LLM Server..." -ForegroundColor Yellow
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Installing Ollama via winget..." -ForegroundColor Yellow
    winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "Ollama found: $($ollama.Source)" -ForegroundColor Green
}

# 4. Pull recommended local 3B model
Write-Host "`n[4/5] Pulling Qwen 2.5 3B Instruct model..." -ForegroundColor Yellow
ollama pull qwen2.5:3b-instruct

# 5. Run Verification Self-Test
Write-Host "`n[5/5] Running verification tests..." -ForegroundColor Yellow
.\.venv\Scripts\python.exe -m unittest discover tests

Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " Deployment Complete! Jarvis is ready to run." -ForegroundColor Green
Write-Host " Try running: .\.venv\Scripts\python.exe -m assistant" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
