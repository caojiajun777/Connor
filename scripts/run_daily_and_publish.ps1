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
    if ($Force) { [void]$argList.Add("--force") }
    if ($DryRun) { [void]$argList.Add("--dry-run") }
    if ($SkipDeps) { [void]$argList.Add("--skip-deps") }

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
