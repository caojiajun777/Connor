# Register / update the Connor daily publish scheduled task (China Standard Time).
# Requires: run PowerShell as the same Windows user that is logged in overnight.
# Wake-from-standby needs wake timers enabled (this script turns them on for the active power plan).

param(
    [string]$TaskName = "ConnorDailyPublish",
    # Primary wake slot. Launcher + Redis wait cover Docker Desktop cold start after wake.
    [string]$At = "06:00",
    [string]$CatchUpAt = "07:00",
    [string]$LateCatchUpAt = "09:00"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $RepoRoot "scripts\run_daily_and_publish.ps1"

if (-not (Test-Path $Launcher)) {
    throw "launcher missing: $Launcher"
}

Write-Host "Enabling wake timers on current power plan..."
try {
    powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 2 | Out-Null
    powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 2 | Out-Null
    powercfg /S SCHEME_CURRENT | Out-Null
} catch {
    Write-Host ("  warning: powercfg wake-timer update failed: {0}" -f $_.Exception.Message)
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"{0}`"" -f $Launcher) `
    -WorkingDirectory $RepoRoot

# Primary 06:00 + morning catch-ups (idempotent if already published)
# + logon catch-up if the overnight wake was missed entirely.
# Settle time after Modern Standby wake is handled in the launcher / ensure_redis.
$daily = New-ScheduledTaskTrigger -Daily -At $At
$catchUp = New-ScheduledTaskTrigger -Daily -At $CatchUpAt
$late = New-ScheduledTaskTrigger -Daily -At $LateCatchUpAt
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logon.Delay = "PT3M"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -Compatibility Win8

# Interactive logon: X collect uses the browser profile in this user session.
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($daily, $catchUp, $late, $logon) `
    -Settings $settings `
    -Principal $principal `
    -Description "Connor AI morning digest: live collect → write → publish (Asia/Shanghai). Triggers: $At, $CatchUpAt, $LateCatchUpAt, and ~3min after logon." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host ""
Write-Host "Registered task: $TaskName"
Write-Host ("  State:        {0}" -f $task.State)
Write-Host ("  Next run:     {0}" -f $info.NextRunTime)
Write-Host ("  WakeToRun:    {0}" -f $task.Settings.WakeToRun)
Write-Host ("  StartWhenAvail:{0}" -f $task.Settings.StartWhenAvailable)
Write-Host ("  Launcher:     {0}" -f $Launcher)
Write-Host ("  Triggers:     {0}, {1}, {2}, AtLogOn+3m" -f $At, $CatchUpAt, $LateCatchUpAt)
Write-Host ""
Write-Host "Notes:"
Write-Host "  - Leave the PC in Sleep/Standby overnight (not fully powered off)."
Write-Host "  - Stay logged into this Windows account (browser collect needs the session)."
Write-Host "  - Docker Desktop should start with Windows so Redis (task-redis) can come up."
Write-Host "  - Already-published days are skipped; catch-up triggers are safe to fire."
Write-Host "  - Manual test:  schtasks /Run /TN $TaskName"
Write-Host "  - Or:          powershell -File `"$Launcher`" -SkipDeps   # or without -SkipDeps"
