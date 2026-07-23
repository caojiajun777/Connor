# Start public stack pieces that are not already listening (idempotent).
# Used by Task Scheduler AtLogOn — keeps aiconnor.cn up after reboot.

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $RepoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("stack_autostart_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $Log -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    Write-Host $line
}

function Test-Listen([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Log "stack autostart begin repo=$RepoRoot"

# Brief settle after login / wake (Docker, network).
Start-Sleep -Seconds 20

# Redis via Docker if missing (best-effort).
try {
    $redis = docker ps --filter "name=task-redis" --format "{{.Names}}" 2>$null
    if (-not $redis) {
        Write-Log "starting docker redis task-redis"
        docker start task-redis 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            docker run -d --name task-redis -p 6379:6379 redis:7-alpine 2>$null | Out-Null
        }
    } else {
        Write-Log "redis already running: $redis"
    }
} catch {
    Write-Log ("redis check skipped: {0}" -f $_.Exception.Message)
}

$env:PYTHONPATH = $RepoRoot
$python = "C:\Python314\python.exe"
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}

if (-not (Test-Listen 8080)) {
    if (-not $python) {
        Write-Log "ERROR: python not found; cannot start API"
    } else {
        Write-Log "starting FastAPI on 127.0.0.1:8080"
        Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList @(
            "-m", "app.cli", "daily", "serve-api", "--host", "127.0.0.1", "--port", "8080"
        ) -WorkingDirectory $RepoRoot | Out-Null
    }
} else {
    Write-Log "API already listening on :8080"
}

$webDir = Join-Path $RepoRoot "web"
if (-not (Test-Listen 3000)) {
    if (-not (Test-Path (Join-Path $webDir ".next"))) {
        Write-Log "building Next.js (first/missing .next)"
        Push-Location $webDir
        npm run build *>> $Log
        Pop-Location
    }
    Write-Log "starting Next on 127.0.0.1:3000"
    $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npmCmd) { $npmCmd = (Get-Command npm -ErrorAction SilentlyContinue).Source }
    if (-not $npmCmd) {
        Write-Log "ERROR: npm not found; cannot start Next"
    } else {
        Start-Process -WindowStyle Hidden -FilePath $npmCmd -ArgumentList @(
            "run", "start", "--", "-p", "3000", "-H", "127.0.0.1"
        ) -WorkingDirectory $webDir | Out-Null
    }
} else {
    Write-Log "Next already listening on :3000"
}

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
    $localCf = Join-Path $env:LOCALAPPDATA "cloudflared\cloudflared.exe"
    if (Test-Path $localCf) { $cloudflared = $localCf }
}
if ($cloudflared) {
    $cfProc = Get-Process cloudflared -ErrorAction SilentlyContinue
    if (-not $cfProc) {
        Write-Log "starting cloudflared tunnel connor-public"
        $cfExe = if ($cloudflared.Source) { $cloudflared.Source } else { "$cloudflared" }
        Start-Process -WindowStyle Hidden -FilePath $cfExe -ArgumentList @(
            "tunnel", "run", "connor-public"
        ) | Out-Null
    } else {
        Write-Log ("cloudflared already running pid={0}" -f ($cfProc | Select-Object -First 1 -ExpandProperty Id))
    }
} else {
    Write-Log "WARNING: cloudflared not found on PATH"
}

Write-Log "stack autostart done"
