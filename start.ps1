# Zvalgas AI — One-Command Launcher
# Usage: .\start.ps1 [mock]
# Example: .\start.ps1 mock    -> uses MOCK_LLM=1 (no Gemini calls)
param([string]$Mode = "")

$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Venv = Join-Path $Backend ".venv"
$Activate = Join-Path $Venv "Scripts\activate.ps1"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  ZVALGAS AI — Battlefield Change Detector     " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ── Check Python ──────────────────────────────────────────────────────────────
$PythonCmd = $null
foreach ($py in @("py -3.9", "python3", "python")) {
    try {
        $ver = (& $py.Split()[0] $py.Split()[1..99] --version 2>&1) -join ""
        if ($ver -match "Python 3\.[89]|Python 3\.1[0-9]") {
            $PythonCmd = $py
            Write-Host "[OK] Found $ver → $py" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Host "[ERROR] Python 3.8+ not found. Install from https://python.org" -ForegroundColor Red
    exit 1
}

# ── Create venv if needed ─────────────────────────────────────────────────────
if (-not (Test-Path $Activate)) {
    Write-Host "[*] Creating Python virtual environment..." -ForegroundColor Yellow
    & $PythonCmd.Split()[0] $PythonCmd.Split()[1..99] -m venv $Venv
}

# ── Activate & install backend deps ───────────────────────────────────────────
Write-Host "[*] Checking backend dependencies..." -ForegroundColor Yellow
$PipExe = Join-Path $Venv "Scripts\pip.exe"
& $PipExe install -r (Join-Path $Backend "requirements.txt") -q --no-warn-script-location

# ── Copy .env if missing ──────────────────────────────────────────────────────
$EnvFile = Join-Path $Backend ".env"
$EnvExample = Join-Path $Root ".env.example"
if (-not (Test-Path $EnvFile) -and (Test-Path $EnvExample)) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "[!] .env created from .env.example — add GEMINI_API_KEY to enable live Gemini." -ForegroundColor Yellow
}

# ── Set MOCK_LLM if requested ─────────────────────────────────────────────────
if ($Mode -eq "mock") {
    $env:MOCK_LLM = "1"
    Write-Host "[*] OFFLINE MODE: MOCK_LLM=1 (fixture data, no Gemini calls)" -ForegroundColor Magenta
}

# ── Check Node.js ─────────────────────────────────────────────────────────────
$NpmCmd = $null
foreach ($npm in @("npm.cmd", "npm")) {
    try {
        $ver = & $npm --version 2>&1
        if ($ver -match "\d+\.\d+") {
            $NpmCmd = $npm
            Write-Host "[OK] Found npm $ver → $npm" -ForegroundColor Green
            break
        }
    } catch {}
}

if ($NpmCmd) {
    Write-Host "[*] Checking frontend dependencies..." -ForegroundColor Yellow
    Push-Location $Frontend
    & $NpmCmd install --silent 2>&1 | Out-Null
    Pop-Location
} else {
    Write-Host "[!] Node.js not found — frontend dev server won't start." -ForegroundColor Yellow
    Write-Host "    Install from https://nodejs.org/ (LTS recommended)" -ForegroundColor Yellow
}

# ── Launch Backend ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Starting backend on http://localhost:8000 ..." -ForegroundColor Cyan
$UvicornExe = Join-Path $Venv "Scripts\uvicorn.exe"
$BackendJob = Start-Process -FilePath $UvicornExe `
    -ArgumentList "app.main:app", "--reload", "--port", "8000" `
    -WorkingDirectory $Backend `
    -PassThru -NoNewWindow

Start-Sleep -Seconds 2
if ($BackendJob.HasExited) {
    Write-Host "[ERROR] Backend failed to start. Check backend logs." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Backend running (PID $($BackendJob.Id))" -ForegroundColor Green

# ── Launch Frontend ────────────────────────────────────────────────────────────
if ($NpmCmd) {
    Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Cyan
    $FrontendJob = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "set", "PATH=C:\Program Files\nodejs;%PATH%", "&", "$NpmCmd", "run", "dev" `
        -WorkingDirectory $Frontend `
        -PassThru -NoNewWindow

    Start-Sleep -Seconds 3
    Write-Host "[OK] Frontend running (PID $($FrontendJob.Id))" -ForegroundColor Green
} else {
    Write-Host "[!] Skipping frontend — serve `frontend/dist` with any static host after `npm run build`." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  Open: http://localhost:5173                  " -ForegroundColor White
Write-Host "  API:  http://localhost:8000/docs             " -ForegroundColor White
if ($Mode -eq "mock") {
    Write-Host "  Mode: OFFLINE (fixture data)                " -ForegroundColor Magenta
} else {
    Write-Host "  Mode: LIVE (set GEMINI_API_KEY in .env)     " -ForegroundColor Green
}
Write-Host "  Press Ctrl+C to stop all services            " -ForegroundColor DarkGray
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

try {
    Wait-Process -Id $BackendJob.Id
} finally {
    Write-Host "[*] Shutting down..." -ForegroundColor Yellow
    if ($NpmCmd -and $FrontendJob -and -not $FrontendJob.HasExited) {
        Stop-Process -Id $FrontendJob.Id -Force -ErrorAction SilentlyContinue
    }
    if (-not $BackendJob.HasExited) {
        Stop-Process -Id $BackendJob.Id -Force -ErrorAction SilentlyContinue
    }
}
