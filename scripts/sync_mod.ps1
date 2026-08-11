# scripts/sync_mod.ps1
# Syncs mod .c files from source to DS local + Workshop cache.
# CRITICAL: Also removes .pak files from Workshop cache to prevent script mismatch.
# Run this EVERY TIME after editing .c files, before restarting the DS.

param(
    [switch]$CheckOnly
)

$ERROR_STOP = $false

# Source directory (where you edit)
$SRC = "Q:\GAMES\Reforger-LLM-Squad\reforger_mod\addons\ReforgerLLMSquad"

# DS local addons
$DS = "Q:\SteamLibrary\steamapps\common\Arma Reforger Server\addons\ReforgerLLMSquad"

# Workshop cache (OVERRIDES DS local -- most important!)
$WS = "C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\ReforgerLLMSquadControl_7E5A1C9B3D8F2406"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Reforger Mod Sync Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Check source files ---
$srcFiles = Get-ChildItem "$SRC\Scripts\Game\*.c" -EA SilentlyContinue
if (-not $srcFiles -or $srcFiles.Count -eq 0) {
    Write-Host "[FATAL] No .c files found in source: $SRC\Scripts\Game\" -ForegroundColor Red
    exit 1
}
Write-Host "[1] Source: $($srcFiles.Count) .c files in $SRC" -ForegroundColor Green

# --- Step 2: Sync to DS local ---
if (-not $CheckOnly) {
    New-Item -Path "$DS\Scripts\Game" -ItemType Directory -Force | Out-Null
    Copy-Item "$SRC\addon.gproj" "$DS\addon.gproj" -Force
    Copy-Item "$SRC\Scripts\Game\*.c" "$DS\Scripts\Game\" -Force
}
$dsFiles = Get-ChildItem "$DS\Scripts\Game\*.c" -EA SilentlyContinue
if (-not $dsFiles -or $dsFiles.Count -ne $srcFiles.Count) {
    Write-Host "[WARN] DS local has $($dsFiles.Count) files, source has $($srcFiles.Count)" -ForegroundColor Yellow
    $ERROR_STOP = $true
} else {
    Write-Host "[2] DS local: $($dsFiles.Count) .c files synced" -ForegroundColor Green
}

# --- Step 3: Sync to Workshop cache ---
if (-not $CheckOnly) {
    New-Item -Path "$WS\Scripts\Game" -ItemType Directory -Force | Out-Null
    Copy-Item "$SRC\Scripts\Game\*.c" "$WS\Scripts\Game\" -Force
}
$wsFiles = Get-ChildItem "$WS\Scripts\Game\*.c" -EA SilentlyContinue
if (-not $wsFiles -or $wsFiles.Count -ne $srcFiles.Count) {
    Write-Host "[WARN] Workshop cache has $($wsFiles.Count) files, source has $($srcFiles.Count)" -ForegroundColor Yellow
    $ERROR_STOP = $true
} else {
    Write-Host "[3] Workshop cache: $($wsFiles.Count) .c files synced" -ForegroundColor Green
}

# --- Step 4: CRITICAL -- Remove .pak files from Workshop cache ---
# .pak files contain OLD compiled scripts from Workbench publishing.
# If .pak exists alongside loose .c files:
#   - DS compiles loose .c (new code) -> 5639 files
#   - Client downloads .pak (old code) -> 5637 files
#   - CRC mismatch -> "script mismatch" error -> client kicked
$pakFiles = Get-ChildItem "$WS\*.pak" -EA SilentlyContinue
if ($pakFiles) {
    Write-Host ""
    Write-Host "[CRITICAL] Found .pak files in Workshop cache!" -ForegroundColor Red
    foreach ($pak in $pakFiles) {
        Write-Host "  - $($pak.Name) ($($pak.Length) bytes)" -ForegroundColor Red
    }
    if (-not $CheckOnly) {
        Write-Host ""
        Write-Host "  Removing .pak files to prevent script mismatch..." -ForegroundColor Yellow
        $pakFiles | Remove-Item -Force
        Write-Host "  .pak files REMOVED" -ForegroundColor Green
    } else {
        Write-Host "  (CheckOnly mode -- not removing. Run without -CheckOnly to fix.)" -ForegroundColor Yellow
        $ERROR_STOP = $true
    }
} else {
    Write-Host "[4] No .pak files in Workshop cache (good)" -ForegroundColor Green
}

# --- Step 5: Also check for stale .rdb ---
$rdbFiles = Get-ChildItem "$WS\*.rdb" -EA SilentlyContinue
if ($rdbFiles) {
    if (-not $CheckOnly) {
        $rdbFiles | Remove-Item -Force
        Write-Host "[5] Removed stale .rdb files" -ForegroundColor Green
    } else {
        Write-Host "[5] Stale .rdb files found (run without -CheckOnly to remove)" -ForegroundColor Yellow
    }
} else {
    Write-Host "[5] No stale .rdb files (good)" -ForegroundColor Green
}

# --- Summary ---
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
if ($ERROR_STOP) {
    Write-Host "  RESULT: ISSUES FOUND -- fix before restarting DS" -ForegroundColor Red
    exit 1
} else {
    Write-Host "  RESULT: ALL SYNCED -- safe to restart DS" -ForegroundColor Green
    Write-Host "  Next: taskkill /F /IM ArmaReforgerServer.exe" -ForegroundColor Gray
    Write-Host "        launch_ds.bat" -ForegroundColor Gray
    Write-Host "        Wait 55s, then check_latest_log.ps1" -ForegroundColor Gray
    exit 0
}
