@echo off
echo ========================================
echo  Reforger LLM Squad Control - Launcher
echo ========================================
echo.

REM Phase 2: Voice pipeline requires admin for global keyboard hook
REM Check if we have admin rights, if not, auto-elevate
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Voice pipeline needs admin for PTT key capture.
    echo        Requesting elevation...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

REM Check if Python bridge is already running
netstat -ano | findstr ":5001" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python bridge is already running on port 5001
) else (
    echo [START] Starting Python bridge...
    start "Reforger-LLM-Bridge" /min cmd /c "cd /d %~dp0\python_bridge && venv\Scripts\python.exe main.py"
    timeout /t 3 /nobreak >nul
    echo [OK] Python bridge started.
)

echo.
echo [INFO] Bridge URL: http://127.0.0.1:5001
echo [INFO] Proxy URL:  http://192.168.1.35:11434/v1
echo [INFO] Model:      llama3
echo.
echo [NEXT] Start the dedicated server with:
echo        launch_ds.bat        (DS is the only dev workflow — see AGENTS.md)
echo.
echo [TIP]  Open http://127.0.0.1:5001/docs for API docs
echo [TIP]  Check python_bridge\bridge.log for details
echo.
exit
