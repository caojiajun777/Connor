#Requires -Version 5.1
<#
.SYNOPSIS
  Print go-live checklist and generate a local ops key if missing.
#>
param(
  [string]$Domain = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Test-Cmd($name) {
  return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host ""
Write-Host "=== Connor go-live checklist ===" -ForegroundColor Cyan
Write-Host ""

$okCloud = Test-Cmd "cloudflared"
$okNode = Test-Cmd "node"
$okPy = Test-Cmd "python"
$built = Test-Path (Join-Path $Root "web\.next")

Write-Host ("[ {0} ] cloudflared installed" -f ($(if ($okCloud) { "OK" } else { "!!" })))
Write-Host ("[ {0} ] node installed" -f ($(if ($okNode) { "OK" } else { "!!" })))
Write-Host ("[ {0} ] python installed" -f ($(if ($okPy) { "OK" } else { "!!" })))
Write-Host ("[ {0} ] web/.next build exists" -f ($(if ($built) { "OK" } else { "--" })))

if (-not $env:CONNOR_OPS_API_KEY) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $generated = [Convert]::ToBase64String($bytes)
  Write-Host ""
  Write-Host "Generated CONNOR_OPS_API_KEY (save it; not written to disk):" -ForegroundColor Yellow
  Write-Host $generated
  Write-Host "Set permanently (current user):"
  Write-Host ('  [Environment]::SetEnvironmentVariable("CONNOR_OPS_API_KEY","{0}","User")' -f $generated)
} else {
  Write-Host "[ OK ] CONNOR_OPS_API_KEY is set in this shell"
}

Write-Host ""
Write-Host "Your steps (must do in browser / Cloudflare):" -ForegroundColor Cyan
Write-Host "  1. Register a domain (Cloudflare Registrar or Namecheap, then Add site to CF)"
Write-Host "  2. Wait until domain status is Active on Cloudflare"
Write-Host "  3. Run:  cloudflared tunnel login"
Write-Host "  4. Tell me your domain — I will finish tunnel config + start scripts"
if ($Domain) {
  Write-Host ""
  Write-Host ("When ready, set SITE URL:") -ForegroundColor Cyan
  Write-Host ('  [Environment]::SetEnvironmentVariable("CONNOR_PUBLIC_SITE_URL","https://{0}","User")' -f $Domain)
  Write-Host ('  [Environment]::SetEnvironmentVariable("CONNOR_PUBLIC_API_BASE","http://127.0.0.1:8080","User")')
  Write-Host ('  [Environment]::SetEnvironmentVariable("CONNOR_MEDIA_PUBLIC_BASE_URL","/media","User")')
}

Write-Host ""
Write-Host "After domain + login are done, local stack:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\run_public_stack.ps1"
Write-Host "  cloudflared tunnel run connor-public"
Write-Host ""
Write-Host "Docs: docs/cloudflare-tunnel.md"
Write-Host ""
