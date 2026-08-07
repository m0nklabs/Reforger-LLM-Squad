# Skill: Arma Reforger debug-workflow (console.log-driven)

> De workflow waarmee de launch-errors van 2026-08-07 in ~4 cycli zijn opgelost.

## 1. Waar staat wat

| Wat | Waar |
|---|---|
| Game-logs | `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<yyyy-mm-dd_hh-mm-ss>\console.log` (LET OP: OneDrive-pad hier) |
| Game-exe | `Q:\SteamLibrary\steamapps\common\Arma Reforger\ArmaReforgerSteam.exe` |
| Base-game addons | `<game>\addons\core\` + `<game>\addons\data\` (packed) |
| Bridge-log | `python_bridge\bridge.log` |

## 2. Log-signatures (sneldiagnose)

| Signatuur | Betekenis |
|---|---|
| console.log ≈ **1145 bytes** | engine-init crash (bv. addon niet gevonden) — game dood voor menu |
| `Game addon '58D0FB3206B6F859' not found` | BASE GAME data niet gevonden → CWD/`./addons` probleem, NIET jouw mod |
| `SCRIPT (E): @"scripts/Game/X.c,REGEL": ...` | compile error; regelnummer klopt |
| `Can't compile "Game" script module!` | ≥1 compile error in module Game; game blijft draaien maar scripts draaien NIET |
| errors in base-game `.c` files ná jouw file | cascade-ruis — fix eerst jouw eerste error |
| log >15KB met BACKEND/PLATFORM regels | gezond; hoofdmenu bereikt |
- De LAATSTE regel van een afgebroken log herhaalt vaak de eerste echte fout.

## 3. Test-cyclus (copy-paste, ~60s per iteratie)

```bat
taskkill /F /IM ArmaReforgerSteam.exe 2>nul
start "" /min cmd /c "Q:\GAMES\Reforger-LLM-Squad\launch_reforger.bat"
```
~50s wachten, dan nieuwste log lezen (PowerShell):
```powershell
$d = Get-ChildItem "$env:USERPROFILE\OneDrive\Documents\My Games\ArmaReforger\logs" -Directory | Sort-Object Name -Descending | Select-Object -First 1
$f = Join-Path $d.FullName 'console.log'
(Get-Item $f).Length                                   # 1145 = crash-signatuur
Select-String $f -Pattern 'SCRIPT.*\(E\)','not found','Module: Game' | ForEach-Object { $_.Line.Trim() }
```

## 4. Praktische valkuilen

- `tasklist | findstr /i ArmaReforgerSteam` — check of de game (nog) draait voor je relauncht.
  Bij een script-compile-error blijft het proces vaak wél leven (error-dialog/scherm) — kill hem.
- Game start via een bat → elke run = nieuw minimized cmd-venster met `pause` (onschuldig).
- `ArmaReforgerWorkbenchSteam` in tasklist = Workbench/Tools draait (andere app dan de game).
- Meerdere log-mappen per uur is normaal; sorteer op naam (= tijd).
- OneDrive sync op "My Games" kan log-writes vertragen; bij twijfel paar seconden extra wachten.
