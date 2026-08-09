# Skill: Arma Reforger debug workflow (console.log-driven)

> The workflow that solved the 2026-08-07 launch errors in ~4 cycles.

## 1. Where things live

| What | Where |
|---|---|
| Game logs | `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<yyyy-mm-dd_hh-mm-ss>\console.log` (NOTE: OneDrive path here) |
| Game exe | `Q:\SteamLibrary\steamapps\common\Arma Reforger\ArmaReforgerSteam.exe` |
| Base-game addons | `<game>\addons\core\` + `<game>\addons\data\` (packed) |
| Bridge log | `python_bridge\bridge.log` |

## 2. Log signatures (quick diagnosis)

| Signature | Meaning |
|---|---|
| console.log ≈ **1145 bytes** | engine-init crash (e.g. addon not found) — game dead before menu |
| `Game addon '58D0FB3206B6F859' not found` | BASE GAME data not found → CWD/`./addons` problem, NOT your mod |
| `SCRIPT (E): @"scripts/Game/X.c,LINE": ...` | compile error; the line number is accurate |
| `Can't compile "Game" script module!` | ≥1 compile error in module Game; game keeps running but scripts do NOT run |
| errors in base-game `.c` files AFTER your file | cascade noise — fix your first error first |
| log >15KB with BACKEND/PLATFORM lines | healthy; main menu reached |
- The LAST line of an aborted log often repeats the first real error.

## 3. Test cycle (~60s per iteration)

```bat
taskkill /F /IM ArmaReforgerSteam.exe 2>nul
start "" /min cmd /c "Q:\GAMES\Reforger-LLM-Squad\launch_reforger.bat"
```
Wait ~50s, then run the one-command check:
```powershell
powershell -NoProfile -File scripts\check_latest_log.ps1
```
It prints the newest log, mod-loaded status, all `(E)` errors and a final OK / NO-GO verdict.

## 4. Practical pitfalls

- `tasklist | findstr /i ArmaReforgerSteam` — check whether the game is (still) running before relaunching.
  On a script-compile error the process often STAYS alive (error dialog/screen) — kill it.
- Starting via a bat → each run spawns a new minimized cmd window with `pause` (harmless).
- `ArmaReforgerWorkbenchSteam` in tasklist = Workbench/Tools running (different app from the game).
- Multiple log folders per hour is normal; sort by name (= time).
- OneDrive sync on "My Games" can delay log writes; when in doubt wait a few extra seconds.

## 5. Play vs Host — the instance destroy trap (2026-08-09)

**This was the hardest-won lesson.** When testing mods:

- **Play (offline)**: starts scenario in the SAME game instance → mod stays loaded (5637 files) → scripts run ✅
- **Host (multiplayer)**: DESTROYS the main-menu instance and creates a NEW one → mod NOT loaded (5633 = vanilla) → scripts DON'T run ❌

The `-addons` CLI parameter only applies to the first game instance. The second instance (created by Host)
loads only base-game addons. Our mod appears in "Available addons" but NOT in "Loaded addons."

**Always test with Play (offline), not Host.**

Log signature for instance destroy:
```
ENGINE: Game destroyed.
ENGINE: Available addons: [our mod listed here]
ENGINE: Loaded addons: [only core + data, NOT our mod]
Module: Game; loaded 5633x files  ← VANILLA
```

## 6. Packed vs unpacked — the silent modded-class trap (2026-08-09)

Packed `.pak` files compile correctly (5637 files, no errors) but **modded class overrides do NOT execute**.
`Print()` output never appears in logs. The mod is "loaded" but modded classes are dead.

**Fix**: delete `data.pak` and `resourceDatabase.rdb` from the mod folder. Use unpacked (loose .c files) only.

```
# BAD - packed, modded classes silently fail:
gproj: '...' guid: '...' (packed)
FileSystem: Adding package '...' (pak count: 1)

# GOOD - unpacked, modded classes execute:
FileSystem: Adding relative directory '...'
```

## 7. Cached workshop mods causing ADDON_LOAD_ERROR (2026-08-09)

If the user previously joined a community server, 100+ cached workshop mods in
`C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\` cause:
```
Kicked from game. reason=5 'ADDON_LOAD_ERROR'
error_failed_to_start_with_mods
```

**Fix**: move all cached mod folders to `addons_disabled/`:
```powershell
$src = 'C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons'
$dst = 'C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons_disabled'
New-Item -ItemType Directory -Path $dst -Force
Get-ChildItem $src -Directory | Move-Item -Destination $dst
```
