#Requires -Version 5.1
<#
.SYNOPSIS
  Start local public stack: FastAPI (:8080) + Next (:3000).
  Run Cloudflare Tunnel separately (or as a Windows service).
#>
param(
  [string]$SiteUrl = $env:CONNOR_PUBLIC_SITE_URL,
  [string]$ApiBase = $(if ($env:CONNOR_PUBLIC_API_BASE) { $env:CONNOR_PUBLIC_API_BASE } else { "http://127.0.0.1:8080" }),
  [string]$MediaBase = $(if ($env:CONNOR_MEDIA_PUBLIC_BASE_URL) { $env:CONNOR_MEDIA_PUBLIC_BASE_URL } else { "/media" }),
  [int]$ApiPort = 8080,
  [int]$WebPort = 3000
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $SiteUrl) {
  Write-Warning "CONNOR_PUBLIC_SITE_URL is empty — set it to https://your.domain before going public."
}
if (-not $env:CONNOR_OPS_API_KEY) {
  Write-Error "CONNOR_OPS_API_KEY is required for public/tunnel use (ops/console must not be keyless behind Next rewrites)."
  exit 1
}

$env:CONNOR_PUBLIC_API_BASE = $ApiBase
$env:CONNOR_MEDIA_PUBLIC_BASE_URL = $MediaBase
if ($SiteUrl) { $env:CONNOR_PUBLIC_SITE_URL = $SiteUrl }

Write-Host "==> Starting FastAPI on 127.0.0.1:$ApiPort"
$api = Start-Process -PassThru -NoNewWindow -FilePath "python" -ArgumentList @(
  "-m", "app.cli", "daily", "serve-api", "--host", "127.0.0.1", "--port", "$ApiPort"
) -WorkingDirectory $Root

Start-Sleep -Seconds 2

$webDir = Join-Path $Root "web"
if (-not (Test-Path (Join-Path $webDir ".next"))) {
  Write-Host "==> Building Next.js (first run)"
  Push-Location $webDir
  npm run build
  Pop-Location
}

Write-Host "==> Starting Next on 127.0.0.1:$WebPort"
$web = Start-Process -PassThru -NoNewWindow -FilePath "npm" -ArgumentList @(
  "run", "start", "--", "-p", "$WebPort", "-H", "127.0.0.1"
) -WorkingDirectory $webDir

Write-Host ""
Write-Host "API pid=$($api.Id)  Web pid=$($web.Id)"
Write-Host "Local:  http://127.0.0.1:$WebPort"
if ($SiteUrl) { Write-Host "Public: $SiteUrl  (via cloudflared tunnel)" }
Write-Host "Press Ctrl+C to stop this watcher (child processes may keep running)."
Write-Host ""

try {
  Wait-Process -Id $api.Id, $web.Id
} finally {
  foreach ($p in @($api, $web)) {
    if ($p -and -not $p.HasExited) {
      Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
  }
}
