# bridge_watchdog.ps1 — D.4: auto-restart the bridge when /health fails.
#
# The bridge is the squad's nervous system; if it dies (crash, OOM, hung
# LLM call), the game silently loses orders and thoughts. This watchdog
# polls /health and restarts the bridge after FailLimit consecutive failures.
# D.3's pending_orders backlog makes restarts safe — queued orders survive.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bridge_watchdog.ps1          # daemon mode (30s interval, 3 strikes)
#   powershell ... -Once                                                                     # single check (testing)
#   powershell ... -Url http://127.0.0.1:5999/health -Once -FailLimit 3                     # test against a dead port
#
# Exit codes (-Once): 0 = healthy, N = unhealthy with N consecutive failures (< FailLimit, no restart)
param(
    [string]$Url = 'http://127.0.0.1:5001/health',
    [int]$FailLimit = 3,
    [int]$IntervalSec = 30,
    [switch]$Once
)

$LogFile = Join-Path $PSScriptRoot 'bridge_watchdog.log'
$RestartScript = Join-Path $PSScriptRoot 'restart_bridge_console.ps1'
$failCount = 0

function Test-BridgeHealth {
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch {
        return $false
    }
}

while ($true) {
    $healthy = Test-BridgeHealth
    $ts = Get-Date -Format 'HH:mm:ss'
    if ($healthy) {
        if ($failCount -gt 0) {
            Add-Content $LogFile "$ts WATCHDOG: bridge recovered after $failCount failure(s)"
        }
        $failCount = 0
    } else {
        $failCount++
        Add-Content $LogFile "$ts WATCHDOG: health check failed ($failCount/$FailLimit): $Url"
        if ($failCount -ge $FailLimit) {
            Add-Content $LogFile "$ts WATCHDOG: RESTARTING bridge (D.3 backlog keeps pending orders)"
            if (Test-Path $RestartScript) {
                & powershell -NoProfile -ExecutionPolicy Bypass -File $RestartScript
            }
            $failCount = 0
        }
    }
    if ($Once) {
        Write-Host "watchdog once: healthy=$healthy failures=$failCount (limit=$FailLimit)"
        exit $failCount
    }
    Start-Sleep -Seconds $IntervalSec
}
