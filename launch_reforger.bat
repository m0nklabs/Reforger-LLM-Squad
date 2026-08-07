@echo off
echo ========================================
echo  Launching Arma Reforger with LLM Mod
echo ========================================
echo.

set "GAME_DIR=Q:\SteamLibrary\steamapps\common\Arma Reforger"
set "MODS_DIR=Q:\GAMES\Reforger-LLM-Squad\reforger_mod\addons"
set "MOD_ID=7E5A1C9B3D8F2406"

REM Check if bridge is running
netstat -ano | findstr ":5001" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Python bridge may not be running.
    echo        Run start_bridge.bat first.
    echo.
)

echo [START] Starting Reforger...
echo [MOD]   %MODS_DIR%\ReforgerLLMSquad
echo.

REM IMPORTANT (see MOD_SETUP.md):
REM  - /d "%GAME_DIR%"  sets the working directory to the game folder. Without it
REM    the engine cannot find its own base game addon (58D0FB3206B6F859) via ./addons
REM    and crashes with "Missing Addon" + "Engine Initialization Error".
REM  - Reforger has NO -mod parameter. Correct: -addonsDir + -addons <GUID>
REM    (wiki: Arma_Reforger:Startup_Parameters)
start "" /d "%GAME_DIR%" "%GAME_DIR%\ArmaReforgerSteam.exe" -addonsDir "%MODS_DIR%" -addons "%MOD_ID%"

echo [OK] Reforger launched.
echo.
echo [CHECK] After startup: verify the newest console.log with
echo         powershell -NoProfile -File scripts\check_latest_log.ps1
echo.
pause
