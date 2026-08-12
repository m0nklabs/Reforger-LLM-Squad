@echo off
REM Sync AGENTS.md (source of truth) to tool-native copies (Windows variant).
cd /d "%~dp0\.."
if exist CLAUDE.md del /f /q CLAUDE.md
if exist .goosehints del /f /q .goosehints
copy /y AGENTS.md CLAUDE.md >nul
copy /y AGENTS.md .goosehints >nul
copy /y AGENTS.md .github\copilot-instructions.md >nul
echo Synced AGENTS.md -^> CLAUDE.md + .goosehints + .github\copilot-instructions.md
