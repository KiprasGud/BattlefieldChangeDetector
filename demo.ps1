# Zvalgas AI - Demo launcher (docs/demo.md). The operator terminal (start.ps1, ports 8000/5173) is not affected.
# Usage:
#   .\demo.ps1          presentation: cached scenes only, full screen; no backend, no AI calls  (= present.cmd)
#   .\demo.ps1 prep     prep mode: live AI on :8010 + prep page on :5174; CACHE STATE writes demo_cache\
param([ValidateSet("present", "prep")][string]$Mode = "present")

$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Cache = if ($env:DEMO_CACHE_DIR) { $env:DEMO_CACHE_DIR } else { Join-Path $Root "demo_cache" }
$ViteJs = "node_modules/vite/bin/vite.js"  # run from $Frontend
$PresentPort = 5175
$PresentUrl = "http://localhost:$PresentPort/demo.html"

function Fail([string]$Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

# True once $Url answers 200, false after $Seconds.
function Wait-Url([string]$Url, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            if ((Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Milliseconds 300
    }
    return $false
}

function Stop-Started($Process) {
    if ($Process -and -not $Process.HasExited) { Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue }
}

# -- Node.js (same lookup as start.ps1: a fresh winget install only reaches PATH in new shells) ---------------
$nodeDirs = @("C:\Program Files\nodejs")
$nodeDirs += Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenJS.NodeJS*\node-*" -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { $_.FullName }
foreach ($d in $nodeDirs) {
    if ((Test-Path (Join-Path $d "node.exe")) -and ($env:PATH -notlike "*$d*")) { $env:PATH = "$d;$env:PATH" }
}
$Node = (Get-Command "node.exe" -ErrorAction SilentlyContinue).Source
if (-not $Node) { Fail "Node.js not found. Install it from https://nodejs.org/ (LTS)." }
if (-not (Test-Path (Join-Path $Frontend $ViteJs))) {
    Write-Host "[*] Installing frontend dependencies..." -ForegroundColor Yellow
    Push-Location $Frontend
    & (Get-Command "npm.cmd").Source install --no-audit --no-fund
    Pop-Location
    if (-not (Test-Path (Join-Path $Frontend $ViteJs))) { Fail "npm install failed." }
}

# =============================================================================================================
if ($Mode -eq "prep") {
    $Uvicorn = Join-Path $Backend ".venv\Scripts\uvicorn.exe"
    if (-not (Test-Path $Uvicorn)) { Fail "Backend environment missing: run .\start.ps1 once to install it." }

    # Prep always runs the real model, fresh on every RUN (no answer cache), and owns no watch folder or batch
    # worker. Set for the child processes only: this shell's values are restored right after they start.
    $prepEnv = [ordered]@{
        MOCK_LLM = "0"; AI_ENABLED = "1"; ANALYSIS_CACHE = "0"; WATCH_ENABLED = "0"; AUTO_BATCH = "0"
        GEMINI_MODEL = "gemini-3.5-flash-lite"
    }
    $saved = @{}
    foreach ($k in $prepEnv.Keys) {
        $saved[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
        [Environment]::SetEnvironmentVariable($k, $prepEnv[$k], "Process")
    }
    try {
        Write-Host "Starting demo prep server on http://localhost:8010 ..." -ForegroundColor Cyan
        $Api = Start-Process -FilePath $Uvicorn -ArgumentList "app.demo_app:app", "--port", "8010" `
            -WorkingDirectory $Backend -PassThru -NoNewWindow
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], "Process") }
    }
    # 127.0.0.1, not localhost: uvicorn listens on IPv4 only, and a refused IPv6 try costs Windows about 2 s.
    if (-not (Wait-Url "http://127.0.0.1:8010/api/health" 60)) {
        Stop-Started $Api
        Fail "Demo prep server did not start on :8010 (port in use? see the log above)."
    }
    $Web = Start-Process -FilePath $Node -ArgumentList $ViteJs, "--config", "vite.demo.config.ts", "--open", "/prep.html" `
        -WorkingDirectory $Frontend -PassThru -NoNewWindow

    Write-Host ""
    Write-Host "  Prep mode:     http://localhost:5174/prep.html" -ForegroundColor White
    Write-Host "  Cache folder:  $Cache" -ForegroundColor White
    Write-Host "  Present with:  present.cmd (or .\demo.ps1)" -ForegroundColor White
    Write-Host "  Press Ctrl+C to stop." -ForegroundColor DarkGray
    try {
        Wait-Process -Id $Api.Id
    } finally {
        Stop-Started $Web
        Stop-Started $Api
    }
    exit 0
}

# =============================================================================================================
# Presentation

# 1. The cache must hold complete scenes: checked here, not in front of the audience.
$Manifest = Join-Path $Cache "manifest.json"
if (-not (Test-Path $Manifest)) { Fail "No cached scenes in $Cache. Run .\demo.ps1 prep and press CACHE STATE first." }
$ids = @((Get-Content $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json).scenes | Where-Object { $_ })
if ($ids.Count -eq 0) { Fail "$Manifest lists no scenes. Cache one in prep mode first." }
$broken = @()
foreach ($id in $ids) {
    $sceneJson = Join-Path (Join-Path $Cache $id) "scene.json"
    $ok = Test-Path $sceneJson
    if ($ok) {
        $files = (Get-Content $sceneJson -Raw -Encoding UTF8 | ConvertFrom-Json).files
        foreach ($f in @($files.image_a, $files.aligned_b)) {
            if (-not $f -or -not (Test-Path (Join-Path (Join-Path $Cache $id) $f))) { $ok = $false }
        }
    }
    if (-not $ok) { $broken += $id }
}
if ($broken.Count) { Fail "Incomplete cached scenes: $($broken -join ', '). Re-cache or delete them in prep mode." }
Write-Host "[OK] $($ids.Count) cached scene(s) in $Cache" -ForegroundColor Green

# 2. Build the presentation bundle when it is missing or older than its sources.
$Built = Join-Path $Frontend "dist-demo\demo.html"
$stale = -not (Test-Path $Built)
if (-not $stale) {
    $builtAt = (Get-Item $Built).LastWriteTime
    $sources = @(Get-ChildItem (Join-Path $Frontend "src") -Recurse -File) +
        @(Get-Item (Join-Path $Frontend "demo.html"), (Join-Path $Frontend "vite.demo.config.ts"))
    $stale = [bool]($sources | Where-Object { $_.LastWriteTime -gt $builtAt } | Select-Object -First 1)
}
if ($stale) {
    Write-Host "[*] Building the presentation..." -ForegroundColor Yellow
    Push-Location $Frontend
    & $Node $ViteJs build --config vite.demo.config.ts --logLevel warn
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "Presentation build failed (see above)." }
}

# 3. Serve it hidden, so no console output shows. A server left over from an earlier run (console closed) is
#    replaced, so the audience never gets an old bundle.
Get-NetTCPConnection -LocalPort $PresentPort -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    $owner = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    if ($owner -and $owner.ProcessName -eq "node") { Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue }
}
$Server = Start-Process -FilePath $Node -ArgumentList $ViteJs, "preview", "--config", "vite.demo.config.ts" `
    -WorkingDirectory $Frontend -WindowStyle Hidden -PassThru
if (-not (Wait-Url $PresentUrl 30)) {
    Stop-Started $Server
    Fail "Presentation server did not start on :$PresentPort (port in use by another program?)."
}

# 4. Full screen: Chrome or Edge as an app window with its own profile (no tabs, toolbars, sign-in or restore
#    prompts), else the default browser.
$exe = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$Browser = $null
$openedAt = Get-Date
if ($exe) {
    $profileDir = Join-Path $env:TEMP "zvalgas-presentation-browser"
    $Browser = Start-Process -FilePath $exe -PassThru -ArgumentList "--app=$PresentUrl", "--start-fullscreen", `
        "--no-first-run", "--no-default-browser-check", "--user-data-dir=`"$profileDir`""
} else {
    Start-Process $PresentUrl
}
Write-Host "[OK] Presenting $PresentUrl" -ForegroundColor Green
Write-Host "     Keys: Enter start, arrows / PageUp / PageDown navigate, F fullscreen, Alt+S light theme." -ForegroundColor DarkGray

try {
    if ($Browser) { Wait-Process -Id $Browser.Id }
    # No browser of our own to wait for (default browser, or the window joined one already open): stop on Enter.
    if (-not $Browser -or ((Get-Date) - $openedAt).TotalSeconds -lt 5) {
        Read-Host "Press Enter to stop the presentation server" | Out-Null
    }
} finally {
    Stop-Started $Server
}
