# Connor daily publish launcher for Windows Task Scheduler.
# Keeps the machine awake for the duration of the job when possible.

param(
    [switch]$Force,
    [switch]$DryRun,
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$env:PYTHONPATH = $RepoRoot

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { return }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if (-not $key) { return }
        if (-not (Test-Path "Env:$key")) {
            Set-Item -Path "Env:$key" -Value $val
        }
    }
}

Import-DotEnv (Join-Path $RepoRoot ".env")

# Fail-forward collect policy for the scheduled daily pipeline.
if (-not $DryRun) {
    $env:CONNOR_COLLECT_AUTO_RETRY = "1"
    $env:CONNOR_COLLECT_RETRY_INTERVAL_SEC = "600"
} elseif (-not $env:CONNOR_COLLECT_RETRY_INTERVAL_SEC) {
    $env:CONNOR_COLLECT_RETRY_INTERVAL_SEC = "600"
}
if (-not $env:CONNOR_COLLECT_RETRY_STOP_BELOW) { $env:CONNOR_COLLECT_RETRY_STOP_BELOW = "5" }
if (-not $env:CONNOR_PUBLISH_DEADLINE_HOUR) { $env:CONNOR_PUBLISH_DEADLINE_HOUR = "12" }
if (-not $env:CONNOR_PUBLISH_DEADLINE_MINUTE) { $env:CONNOR_PUBLISH_DEADLINE_MINUTE = "0" }
if (-not $env:CONNOR_PUBLISH_DEADLINE_RESERVE_MIN) { $env:CONNOR_PUBLISH_DEADLINE_RESERVE_MIN = "90" }
if (-not $env:CONNOR_MCP_RATE_LIMIT_RETRIES) { $env:CONNOR_MCP_RATE_LIMIT_RETRIES = "0" }
if (-not $env:CONNOR_COLLECT_ACCOUNT_PAUSE_MS) { $env:CONNOR_COLLECT_ACCOUNT_PAUSE_MS = "1000" }

$LogDir = Join-Path $RepoRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$WrapperLog = Join-Path $LogDir "task_wrapper_$Stamp.log"

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    try {
        Add-Content -Path $WrapperLog -Value $line -Encoding UTF8 -ErrorAction Stop
    } catch {
        # Still surface to host stdout for Task Scheduler history capture.
    }
    Write-Host $line
}

# Log before any P/Invoke so early failures are still visible.
Write-Log "wrapper start repo=$RepoRoot pid=$PID user=$env:USERNAME"

# After Modern Standby wake, give network / Docker a brief head start before probes.
$settleSec = 45
if ($env:CONNOR_TASK_SETTLE_SEC) {
    $settleSec = [int]$env:CONNOR_TASK_SETTLE_SEC
}
if ($settleSec -gt 0) {
    Write-Log "settle sleep ${settleSec}s (post-wake)"
    Start-Sleep -Seconds $settleSec
}

try {
    if (-not ("ConnorTask.Power" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace ConnorTask {
  public static class Power {
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
    public const uint ES_CONTINUOUS = 0x80000000;
    public const uint ES_SYSTEM_REQUIRED = 0x00000001;
    public const uint ES_AWAYMODE_REQUIRED = 0x00000040;
  }
}
"@
    }
    [void][ConnorTask.Power]::SetThreadExecutionState(
        [ConnorTask.Power]::ES_CONTINUOUS -bor
        [ConnorTask.Power]::ES_SYSTEM_REQUIRED -bor
        [ConnorTask.Power]::ES_AWAYMODE_REQUIRED
    )
    Write-Log "execution state: system+away requested"
} catch {
    Write-Log ("execution state setup skipped: {0}" -f $_.Exception.Message)
}

$exitCode = 1
try {
    $python = "C:\Python314\python.exe"
    if (-not (Test-Path $python)) {
        $python = (Get-Command python -ErrorAction Stop).Source
    }
    Write-Log "python=$python"

    $argList = [System.Collections.Generic.List[string]]::new()
    $argList.Add((Join-Path $RepoRoot "scripts\daily_and_publish.py"))
    # Production defaults: same-day posts only; tolerate small collect gaps + inline auto-retry.
    [void]$argList.Add("--split-by-day")
    [void]$argList.Add("--accept-gap")
    if ($Force) { [void]$argList.Add("--force") }
    if ($DryRun) { [void]$argList.Add("--dry-run") }
    if ($SkipDeps) { [void]$argList.Add("--skip-deps") }

    Write-Log (
        "collect policy auto_retry={0} interval_sec={1} stop_below={2} publish_deadline={3}:{4} reserve_min={5}" -f
        $env:CONNOR_COLLECT_AUTO_RETRY,
        $env:CONNOR_COLLECT_RETRY_INTERVAL_SEC,
        $env:CONNOR_COLLECT_RETRY_STOP_BELOW,
        $env:CONNOR_PUBLISH_DEADLINE_HOUR,
        $env:CONNOR_PUBLISH_DEADLINE_MINUTE,
        $env:CONNOR_PUBLISH_DEADLINE_RESERVE_MIN
    )
    Write-Log ("launch: {0} {1}" -f $python, ($argList -join " "))

    # Start-Process -Wait gives a reliable exit code under Task Scheduler
    # (native & + $LASTEXITCODE is flaky for long jobs).
    $proc = Start-Process `
        -FilePath $python `
        -ArgumentList $argList.ToArray() `
        -WorkingDirectory $RepoRoot `
        -Wait `
        -PassThru `
        -NoNewWindow

    if ($null -eq $proc.ExitCode) {
        $exitCode = 1
        Write-Log "python exit=<null> treating as failure"
    } else {
        $exitCode = [int]$proc.ExitCode
        Write-Log "python exit=$exitCode wrapper_log=$WrapperLog"
    }
}
catch {
    Write-Log ("wrapper fatal: {0}" -f $_.Exception.Message)
    $exitCode = 1
}
finally {
    try {
        if (("ConnorTask.Power" -as [type])) {
            [void][ConnorTask.Power]::SetThreadExecutionState(
                [ConnorTask.Power]::ES_CONTINUOUS
            )
        }
    } catch {
        # ignore
    }
}

exit $exitCode
