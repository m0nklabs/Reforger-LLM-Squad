# dev_loop.ps1 -- Autonomous overnight development loop for Reforger-LLM-Squad.
#
# Runs `pi -p "<dev prompt>"` repeatedly in the project root. Each iteration:
#   - pi reads AGENTS.md (roadmap) automatically as context
#   - picks the next implementable roadmap item, implements, tests, commits, pushes
#   - says "DEVELOPMENT LOOP DONE" when nothing meaningful is left
#
# Stop conditions (whichever comes first):
#   - output contains "DEVELOPMENT LOOP DONE"
#   - two consecutive iterations with a clean git tree (agent did nothing)
#   - MaxIterations reached
#   - MaxDuration reached
#   - pi fails to start
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev_loop.ps1
#         [-MaxIterations 30] [-MaxDurationHours 8] [-IterationTimeoutSec 900]

param(
    [int]$MaxIterations = 30,
    [int]$MaxDurationHours = 8,
    [int]$IterationTimeoutSec = 900
)

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogFile = Join-Path $PSScriptRoot 'dev_loop.log'
$StartTime = Get-Date
$EndTime = $StartTime.AddHours($MaxDurationHours)

function Write-Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-GitDirty {
    Push-Location $ProjectRoot
    $dirty = (git status --porcelain 2>$null | Measure-Object -Line).Lines
    Pop-Location
    return $dirty
}

function Invoke-PiIteration([int]$iteration) {
    $devPrompt = @"
You are in an autonomous overnight development loop for the Reforger-LLM-Squad project (Q:\GAMES\Reforger-LLM-Squad).
Read AGENTS.md first -- especially the "Development roadmap" section (Phases V/A/B/C/D/E) and the "Critical rules".
Pick the highest-priority item that can be completed WITHOUT a live game client connected.
Bridge-only work, unit tests, dashboard, and code-quality fixes are fine; live-game verification is NOT possible right now.

Workflow per iteration:
1. Choose ONE item from the roadmap (or a clear bug from the rules). Do not start huge multi-item refactors.
2. Implement it. Test it with the running bridge (http://127.0.0.1:5001) or with unit tests. Fix what you break.
3. Update AGENTS.md: move the item to Completed, add new lessons as rules if applicable.
4. Run: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-agent-docs.bat
5. Commit (short, feature-scoped message) and push to origin main.

Hard constraints:
- NEVER restart the DS (ArmaReforgerServer.exe) or run sync_mod.ps1 / launch_ds.bat.
- NEVER publish to the BI Workshop.
- NEVER commit config.json (secrets) or use git add -f on ignored files.
- NEVER change the addon GUID or the base-game GUID 58D0FB3206B6F859.
- Do not wait for or require a connected game client.
- Keep the bridge running; restart it via scripts\restart_bridge_console.ps1 if you changed bridge code.

When you are done (all remaining roadmap items are blocked on a live client, or nothing meaningful is left):
respond with exactly: DEVELOPMENT LOOP DONE
and make no further changes.
"@

    Write-Log "=== Iteration $iteration starting (elapsed $([math]::Round(((Get-Date) - $StartTime).TotalHours, 1))h) ==="

    # Run pi in print mode, capturing output.
    # Note: 'pi' is a .cmd shim - Start-Process can't exec it directly, and
    # the long prompt would need fragile quoting. So: write the prompt to a
    # temp file and pipe it via stdin (pi -p merges piped stdin into the prompt).
    $promptFile = Join-Path $PSScriptRoot "dev_loop_prompt_$iteration.txt"
    Set-Content -Path $promptFile -Value $devPrompt -Encoding UTF8
    $outFile = Join-Path $PSScriptRoot "dev_loop_iter_$iteration.out"
    $errFile = "$outFile.err"
    $cmdLine = "pi -p --no-session < `"$promptFile`" > `"$outFile`" 2> `"$errFile`""
    $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList @('/c', $cmdLine) `
        -WorkingDirectory $ProjectRoot -PassThru -NoNewWindow

    if (-not $proc.WaitForExit($IterationTimeoutSec * 1000)) {
        Write-Log "WARNING: iteration $iteration timed out after ${IterationTimeoutSec}s -- killing pi"
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        # cmd spawns pi as a child; kill the tree too
        taskkill /PID $($proc.Id) /T /F 2>&1 | Out-Null
        Start-Sleep -Seconds 2
    }
    Remove-Item $promptFile -Force -ErrorAction SilentlyContinue

    $output = ''
    if (Test-Path $outFile) {
        $output = (Get-Content $outFile -Raw -Encoding UTF8) -join "`n"
        Remove-Item $outFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path "$outFile.err") {
        $errOut = Get-Content "$outFile.err" -Raw -Encoding UTF8
        Remove-Item "$outFile.err" -Force -ErrorAction SilentlyContinue
        if ($errOut) { Write-Log "pi stderr: $($errOut.Substring(0, [Math]::Min(300, $errOut.Length)))" }
    }

    # Log a short summary of what pi said
    $summary = ($output -replace "`r", '').Trim()
    if ($summary.Length -gt 0) {
        $tail = $summary.Substring([Math]::Max(0, $summary.Length - 500))
        Write-Log "pi output tail: $tail"
    } else {
        Write-Log "WARNING: no output from pi"
    }

    return $output
}

# ---- Main loop ----
Write-Log "=== DEV LOOP STARTED -- max $MaxIterations iterations, until $($EndTime.ToString('yyyy-MM-dd HH:mm:ss')) ==="
Write-Log "Project: $ProjectRoot | log: $LogFile"

$cleanRuns = 0
for ($i = 1; $i -le $MaxIterations; $i++) {
    if ((Get-Date) -gt $EndTime) {
        Write-Log "TIME LIMIT REACHED ($($EndTime.ToString('HH:mm'))). Stopping."
        break
    }

    $dirtyBefore = Get-GitDirty
    $output = Invoke-PiIteration -iteration $i

    if ($output -match 'DEVELOPMENT LOOP DONE') {
        Write-Log "pi reported DONE. Stopping."
        break
    }

    # Safety net: commit anything the agent left uncommitted
    $dirtyAfter = Get-GitDirty
    if ($dirtyAfter -gt 0) {
        Write-Log "Uncommitted changes remain ($dirtyAfter) -- auto-committing as safety net"
        Push-Location $ProjectRoot
        git add -A 2>&1 | Out-Null
        git commit -m "dev loop: auto-commit leftover changes (iteration $i)" 2>&1 | Out-Null
        git push origin main 2>&1 | Out-Null
        Pop-Location
    }

    # Stop if nothing changed for two consecutive iterations
    if ($dirtyBefore -eq 0 -and $dirtyAfter -eq 0) {
        $cleanRuns++
        Write-Log "Iteration $i produced no changes (clean runs: $cleanRuns)"
        if ($cleanRuns -ge 2) {
            Write-Log "Two clean runs in a row -- nothing left to do. Stopping."
            break
        }
    } else {
        $cleanRuns = 0
    }

    Start-Sleep -Seconds 5
}

Write-Log "=== DEV LOOP ENDED after $i iterations ($([math]::Round(((Get-Date) - $StartTime).TotalHours, 1))h) ==="
