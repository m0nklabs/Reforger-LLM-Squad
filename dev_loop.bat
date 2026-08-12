@echo off
echo ========================================
echo  Reforger-LLM-Squad — Night Dev Loop
echo ========================================
echo.
echo  Runs pi in an autonomous loop until:
echo   - pi says "DEVELOPMENT LOOP DONE"
echo   - 2 clean runs (nothing left to do)
echo   - 30 iterations or 8 hours
echo.
echo  Log: scripts\dev_loop.log
echo  NOTE: bridge must be running (start_bridge.bat).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev_loop.ps1"
echo.
echo  Loop finished. See scripts\dev_loop.log for details.
exit
