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
