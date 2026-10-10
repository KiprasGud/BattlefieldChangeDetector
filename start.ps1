# Zvalgas AI - One-Command Launcher
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
Write-Host "  ZVALGAS AI - Battlefield Change Detector     " -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# -- Check Python --------------------------------------------------------------
# Candidates: PATH commands first, then default per-user / machine installs
# (winget/python.org installers do not always add Python to PATH).
# The WindowsApps "python.exe" is a Microsoft Store stub, never a real interpreter.
$PythonExe = $null
$candidates = @()
foreach ($name in @("python", "python3")) {
    Get-Command $name -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch "WindowsApps" } |
        ForEach-Object { $candidates += $_.Source }
}
$pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
if ($pyLauncher) {
    try { $candidates += (& py -3 -c "import sys; print(sys.executable)" 2>$null) } catch {}
}
$candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "C:\Program Files\Python3*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | ForEach-Object { $_.FullName }

foreach ($exe in $candidates) {
    if (-not $exe) { continue }
    try {
        $ver = (& $exe --version 2>&1) -join ""
        if ($ver -match "Python 3\.(9|1[0-9])") {
            $PythonExe = $exe
            Write-Host "[OK] Found $ver -> $exe" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $PythonExe) {
    Write-Host "[ERROR] Python 3.9+ not found. Install: winget install -e --id Python.Python.3.12" -ForegroundColor Red
    exit 1
}

# -- Create venv if needed -----------------------------------------------------
if (-not (Test-Path $Activate)) {
    Write-Host "[*] Creating Python virtual environment..." -ForegroundColor Yellow
    & $PythonExe -m venv $Venv
}

# -- Activate & install backend deps -------------------------------------------
Write-Host "[*] Checking backend dependencies..." -ForegroundColor Yellow
$PipExe = Join-Path $Venv "Scripts\pip.exe"
& $PipExe install -r (Join-Path $Backend "requirements.txt") -q --no-warn-script-location

# -- Copy .env if missing ------------------------------------------------------
$EnvFile = Join-Path $Backend ".env"
$EnvExample = Join-Path $Root ".env.example"
if (-not (Test-Path $EnvFile) -and (Test-Path $EnvExample)) {
    Copy-Item $EnvExample $EnvFile
    Write-Host "[!] .env created from .env.example - add GEMINI_API_KEY to enable live Gemini." -ForegroundColor Yellow
}

# -- Set MOCK_LLM if requested -------------------------------------------------
if ($Mode -eq "mock") {
    $env:MOCK_LLM = "1"
    Write-Host "[*] OFFLINE MODE: MOCK_LLM=1 (fixture data, no Gemini calls)" -ForegroundColor Magenta
}

# -- Check Node.js -------------------------------------------------------------
# A fresh winget install only reaches PATH in new shells; add known install dirs for this session.
$nodeDirs = @("C:\Program Files\nodejs")
$nodeDirs += Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenJS.NodeJS*\node-*" -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { $_.FullName }
foreach ($d in $nodeDirs) {
    if ((Test-Path (Join-Path $d "npm.cmd")) -and ($env:PATH -notlike "*$d*")) { $env:PATH = "$d;$env:PATH" }
}

$NpmCmd = $null
$npmFound = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
if ($npmFound) {
    $ver = & $npmFound.Source --version 2>$null
    if ($ver -match "\d+\.\d+") {
        $NpmCmd = $npmFound.Source
        Write-Host "[OK] Found npm $ver -> $NpmCmd" -ForegroundColor Green
    }
}

if ($NpmCmd) {
    if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
        Write-Host "[*] Installing frontend dependencies..." -ForegroundColor Yellow
        Push-Location $Frontend
        & $NpmCmd install --no-audit --no-fund
        Pop-Location
    }
} else {
    Write-Host "[!] Node.js not found - frontend dev server won't start." -ForegroundColor Yellow
    Write-Host "    Install from https://nodejs.org/ (LTS recommended)" -ForegroundColor Yellow
}

# -- Launch Backend ------------------------------------------------------------
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

# -- Launch Frontend ------------------------------------------------------------
if ($NpmCmd) {
    Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Cyan
    # Child inherits this session's PATH (with the Node dir added above).
    $FrontendJob = Start-Process -FilePath $NpmCmd `
        -ArgumentList "run", "dev" `
        -WorkingDirectory $Frontend `
        -PassThru -NoNewWindow

    Start-Sleep -Seconds 3
    Write-Host "[OK] Frontend running (PID $($FrontendJob.Id))" -ForegroundColor Green
} else {
    Write-Host '[!] Skipping frontend - run ''npm run build'' and serve frontend/dist with any static host.' -ForegroundColor Yellow
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
