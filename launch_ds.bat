@echo off
echo ========================================
echo  Arma Reforger DS - LLM Squad Server
echo ========================================
echo.

set "DS_DIR=Q:\SteamLibrary\steamapps\common\Arma Reforger Server"
set "MODS_DIR=Q:\GAMES\Reforger-LLM-Squad\reforger_mod\addons"
set "MOD_GUID=7E5A1C9B3D8F2406"
set "CONFIG=%DS_DIR%\server.json"

REM Check if bridge is running
netstat -ano | findstr ":5001" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Python bridge may not be running.
    echo        Run start_bridge.bat first.
    echo.
)

echo [START] Starting Dedicated Server...
echo [MOD]  GUID: %MOD_GUID% (from BI Workshop)
echo.

REM The mod is published to BI Workshop as unlisted.
REM game.mods[] in server.json references the addon GUID.
REM DS downloads the mod from BI Workshop on startup.
start "" /d "%DS_DIR%" "%DS_DIR%\ArmaReforgerServer.exe" -config "%CONFIG%" -nographics -logLevel normal

echo [OK] DS launched.
echo [CHECK] Verify with:
echo   powershell -NoProfile -File scripts\check_latest_log.ps1
echo [RCON]  port 19999, password "llmadmin"
echo [GAME]  RPL port 2001
echo.
pause
