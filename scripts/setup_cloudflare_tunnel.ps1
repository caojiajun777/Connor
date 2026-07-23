#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$env:Path = "$env:LOCALAPPDATA\cloudflared;$env:Path"
$Domain = "aiconnor.cn"
$TunnelName = "connor-public"

if (-not (Test-Path "$env:USERPROFILE\.cloudflared\cert.pem")) {
  Write-Host "ERROR: Run cloudflared tunnel login first." -ForegroundColor Red
  exit 1
}

$existing = cloudflared tunnel list 2>&1 | Out-String
if ($existing -notmatch $TunnelName) {
  Write-Host "Creating tunnel $TunnelName ..."
  cloudflared tunnel create $TunnelName
} else {
  Write-Host "Tunnel $TunnelName already exists"
}

$list = cloudflared tunnel list --output json | ConvertFrom-Json
$tunnel = $list | Where-Object { $_.name -eq $TunnelName } | Select-Object -First 1
if (-not $tunnel) { throw "Tunnel not found after create" }
$uuid = $tunnel.id
Write-Host "Tunnel UUID: $uuid"

Write-Host "Routing DNS $Domain -> $TunnelName"
cloudflared tunnel route dns $TunnelName $Domain
# also www optional
try { cloudflared tunnel route dns $TunnelName "www.$Domain" } catch { Write-Host "www route skipped/exists" }

$cred = Join-Path $env:USERPROFILE ".cloudflared\$uuid.json"
if (-not (Test-Path $cred)) { throw "Missing credentials file: $cred" }

$config = @"
tunnel: $uuid
credentials-file: $cred

ingress:
  - hostname: $Domain
    service: http://127.0.0.1:3000
  - hostname: www.$Domain
    service: http://127.0.0.1:3000
  - service: http_status:404
"@
$configPath = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
Set-Content -Path $configPath -Value $config -Encoding UTF8
Write-Host "Wrote $configPath"
Get-Content $configPath
Write-Host ""
Write-Host "Next: start stack + tunnel"
