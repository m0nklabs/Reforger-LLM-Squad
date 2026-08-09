@echo off
echo ========================================
echo  Arma Reforger DS - LLM Squad Server
echo ========================================
echo.

set "DS_DIR=Q:\SteamLibrary\steamapps\common\Arma Reforger Server"
set "MODS_DIR=Q:\GAMES\Reforger-LLM-Squad\reforger_mod\addons"
set "MOD_ID=7E5A1C9B3D8F2406"
set "CONFIG=%DS_DIR%\server.json"

REM Sync mod to DS addons folder
echo [SYNC] Copying mod to DS addons...
xcopy "%MODS_DIR%\ReforgerLLMSquad" "%DS_DIR%\addons\ReforgerLLMSquad\" /E /I /Y /Q >nul 2>&1
echo [OK] Mod synced.

REM Start DS
echo [START] Starting Dedicated Server...
echo [CONFIG] %CONFIG%
echo.

REM IMPORTANT: -config + -addons CANNOT be combined (DS hard check in build 190965)
REM The mod must either be:
REM   A. Published to Steam Workshop (use game.mods[] in server.json)
REM   B. Packed as .pak with resourceDatabase.rdb (loads as base addon, no -addons needed)
REM Currently using -config + -addonsDir (mod is available but NOT loaded until packed/published)
start "" /d "%DS_DIR%" "%DS_DIR%\ArmaReforgerServer.exe" -config "%CONFIG%" -addonsDir "%DS_DIR%\addons" -nographics -logLevel normal

echo [OK] DS launched.
echo [CHECK] Verify with:
echo   powershell -NoProfile -File scripts\check_latest_log.ps1
echo [RCON]  rcon port 19999, password "llmadmin"
echo [GAME]  RPL port 2001
echo.
pause
