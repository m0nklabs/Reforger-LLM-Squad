@echo off
REM Sync AGENTS.md (source of truth) naar tool-native kopieen (Windows-variant).
cd /d "%~dp0\.."
if exist CLAUDE.md del /f /q CLAUDE.md
if exist .goosehints del /f /q .goosehints
copy /y AGENTS.md CLAUDE.md >nul
copy /y AGENTS.md .goosehints >nul
echo Synced AGENTS.md -^> CLAUDE.md + .goosehints
