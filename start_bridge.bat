@echo off
echo ========================================
echo  Reforger LLM Squad Control - Launcher
echo ========================================
echo.

REM Check if Python bridge is already running
netstat -ano | findstr ":5001" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python bridge is already running on port 5001
) else (
    echo [START] Starting Python bridge...
    start "Reforger-LLM-Bridge" /min cmd /k "cd /d %~dp0\python_bridge && venv\Scripts\python.exe main.py"
    timeout /t 3 /nobreak >nul
    echo [OK] Python bridge started.
)

echo.
echo [INFO] Bridge URL: http://127.0.0.1:5001
echo [INFO] Proxy URL:  http://192.168.1.35:11434/v1
echo [INFO] Model:      llama3
echo.
echo [NEXT] Launch Arma Reforger with:
echo        launch_reforger.bat
echo        (uses -addonsDir + -addons, NEVER -mod; see MOD_SETUP.md)
echo.
echo [TIP]  Open http://127.0.0.1:5001/docs for API docs
echo [TIP]  Check python_bridge\bridge.log for details
echo.
pause
