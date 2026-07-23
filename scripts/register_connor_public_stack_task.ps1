# Register AtLogOn task so API + Next + cloudflared come back after reboot/login.

param(
    [string]$TaskName = "ConnorPublicStack"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $RepoRoot "scripts\start_public_stack_bg.ps1"

if (-not (Test-Path $Launcher)) {
    throw "launcher missing: $Launcher"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ("-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"{0}`"" -f $Launcher) `
    -WorkingDirectory $RepoRoot

$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logon.Delay = "PT1M"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -Compatibility Win8

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $logon `
    -Settings $settings `
    -Principal $principal `
    -Description "Start Connor public stack (API :8080, Next :3000, cloudflared) ~1min after logon." `
    -Force | Out-Null

# Also re-assert daily publish logon catch-up is present.
& (Join-Path $PSScriptRoot "register_connor_daily_task.ps1")

Write-Host ""
Write-Host "Registered task: $TaskName (AtLogOn + 1 minute)"
Write-Host "Manual test: schtasks /Run /TN $TaskName"
Write-Host ""
Write-Host "Optional (Admin): install tunnel as a Windows service so it survives without logon:"
Write-Host "  cloudflared service install"
