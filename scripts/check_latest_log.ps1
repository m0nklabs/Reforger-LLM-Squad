# check_latest_log.ps1 — Diagnose the newest ArmaReforger console.log
# Usage:  powershell -NoProfile -File scripts\check_latest_log.ps1
# Exit 0 = OK, 1 = problem found. Background: docs/skills/reforger-debugging.md

$logRoot = Join-Path $env:USERPROFILE 'OneDrive\Documents\My Games\ArmaReforger\logs'
if (-not (Test-Path $logRoot)) {
    $logRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'My Games\ArmaReforger\logs'
}
$d = Get-ChildItem $logRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
if (-not $d) { Write-Output ('NO-GO: no log folder found under ' + $logRoot); exit 1 }

$f = Join-Path $d.FullName 'console.log'
if (-not (Test-Path $f)) { Write-Output ('NO-GO: no console.log in ' + $d.FullName); exit 1 }
$size = (Get-Item $f).Length
Write-Output ('LOG: ' + $d.Name + '  (' + $size + ' bytes)')

if ($size -lt 2000) {
    Write-Output 'NO-GO: log < 2000 bytes = engine-init crash signature. Full log follows:'
    Get-Content $f
    exit 1
}

Write-Output '--- Mod loaded? ---'
$mod = Select-String -Path $f -Pattern 'ReforgerLLMSquad'
if ($mod) { $mod | Select-Object -First 3 | ForEach-Object { $_.Line.Trim() } } else { Write-Output '(mod NOT found in log!)' }

Write-Output '--- All (E) errors (base-game menu errors can be harmless) ---'
$errors = Select-String -Path $f -Pattern '\(E\)' | ForEach-Object { $_.Line.Trim() }
if ($errors) { $errors | Select-Object -First 12 | ForEach-Object { $_ } } else { Write-Output '(none)' }

$compileFail = Select-String -Path $f -Pattern "Can't compile" -SimpleMatch -Quiet
$ours = $errors | Select-String -Pattern 'LLMBridge','ReforgerLLMSquad'

if ($compileFail -or $ours -or -not $mod) {
    Write-Output 'NO-GO: compile error or errors in our files — fix the FIRST error in our .c file (the rest is often cascade)'
    exit 1
}
Write-Output 'OK: mod loaded, no compile errors, no errors in our files'
exit 0
