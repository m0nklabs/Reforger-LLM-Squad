# check_latest_log.ps1 — Diagnose van de nieuwste ArmaReforger console.log
# Gebruik:  powershell -NoProfile -File scripts\check_latest_log.ps1
# Exit 0 = OK, 1 = probleem. Achtergrond: docs/skills/reforger-debugging.md

$logRoot = Join-Path $env:USERPROFILE 'OneDrive\Documents\My Games\ArmaReforger\logs'
if (-not (Test-Path $logRoot)) {
    $logRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'My Games\ArmaReforger\logs'
}
$d = Get-ChildItem $logRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
if (-not $d) { Write-Output ('NO-GO: geen log-map gevonden onder ' + $logRoot); exit 1 }

$f = Join-Path $d.FullName 'console.log'
if (-not (Test-Path $f)) { Write-Output ('NO-GO: geen console.log in ' + $d.FullName); exit 1 }
$size = (Get-Item $f).Length
Write-Output ('LOG: ' + $d.Name + '  (' + $size + ' bytes)')

if ($size -lt 2000) {
    Write-Output 'NO-GO: log < 2000 bytes = engine-init crash-signatuur. Volledige log volgt:'
    Get-Content $f
    exit 1
}

Write-Output '--- Mod geladen? ---'
$mod = Select-String -Path $f -Pattern 'ReforgerLLMSquad'
if ($mod) { $mod | Select-Object -First 3 | ForEach-Object { $_.Line.Trim() } } else { Write-Output '(mod NIET in log gevonden!)' }

Write-Output '--- Alle (E) errors (base-game menu-errors kunnen onschuldig zijn) ---'
$errors = Select-String -Path $f -Pattern '\(E\)' | ForEach-Object { $_.Line.Trim() }
if ($errors) { $errors | Select-Object -First 12 | ForEach-Object { $_ } } else { Write-Output '(geen)' }

$compileFail = Select-String -Path $f -Pattern "Can't compile" -SimpleMatch -Quiet
$ours = $errors | Select-String -Pattern 'LLMBridge','ReforgerLLMSquad'

if ($compileFail -or $ours -or -not $mod) {
    Write-Output 'NO-GO: compile-error of errors in onze files — fix de EERSTE error in onze .c file (rest is vaak cascade)'
    exit 1
}
Write-Output 'OK: mod geladen, geen compile-errors, geen errors in onze files'
exit 0
