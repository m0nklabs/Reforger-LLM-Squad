# AGENTS.md — Reforger-LLM-Squad

> Canonical AI-agent context voor deze repo. LEES DIT EERST.
> Claude Code: `CLAUDE.md` (sync-copy). Goose: `.goosehints` (sync-copy). Copilot: `.github/copilot-instructions.md`.
> Dit bestand = source of truth. Na wijziging: `scripts\sync-agent-docs.bat` (of .sh) draaien.

## Wat dit project is
LLM-gestuurde squad-control voor Arma Reforger. Een Enforce-script mod in de game praat via
HTTP met een lokale FastAPI bridge, die requests doorgeeft aan een LLM (Ollama-compatible proxy
op het LAN). Fase 1 = REST + squad control (nog geen voice).

## Stack
- **Game-mod**: Arma Reforger (build 190965), Enforce script (`.c`). Addon = `reforger_mod/addons/ReforgerLLMSquad/` met `addon.gproj` (GameProject-formaat)
- **Bridge**: Python 3.11, FastAPI + uvicorn + pydantic + openai-client. Entry: `python_bridge/main.py`. Config: `python_bridge/config.json` (GITIGNORED — kopieer uit `config.example.json`)
- **LLM**: Ollama-compatible proxy `http://192.168.1.35:11434/v1`, model `llama3`
- **Platform**: Windows-only paden. Game-dir: `Q:\SteamLibrary\steamapps\common\Arma Reforger`
- **Logs**: `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<timestamp>\console.log`
- **Launchers**: `start_bridge.bat` (bridge, poort 5001), `launch_reforger.bat` (game + mod)

## Critical rules (hard-won — niet overtreden)
1. **GUID `58D0FB3206B6F859` = de BASE GAME** (`addons\data\ArmaReforger.gproj`). NOOIT als eigen mod-GUID gebruiken. Onze mod-GUID: `7E5A1C9B3D8F2406` (in `addon.gproj`).
2. **Reforger kent GEEN `-mod` parameter.** Mods laden: `-addonsDir <parent-van-modmap> -addons <GUID>`.
3. **Working directory bij starten = game-dir** (`start "" /d "<game_dir>" ...`). Anders vindt de engine `./addons` niet → "Missing Addon 58D0FB3206B6F859" + Engine Initialization Error.
4. **Addon-format**: map met `addon.gproj` (`GameProject { ID/GUID/Dependencies }`). De engine leest GEEN zelfverzonnen `addon.json`/`gproj.conf`.
5. **Test = empirisch, altijd**: kill game → `launch_reforger.bat` → ~50s → nieuwste `console.log`. Crash-signatuur: log ≈1145 bytes. `SCRIPT (E)` in base-game `.c` files ná jouw file = cascade-ruis; fix eerst JOUW eerste error.
6. **Enforce**: geen geneste classes; `class`/`modded class` (`modclass` bestaat niet); geen `ref` op engine-types met private destructor (`RestContext`); `World.GetGameTime()` bestaat niet → eigen timer via `timeslice`.
7. **REST in-game**: `GetGame().GetRestApi().GetContext(url)` + `GET(cb, path)` / `POST(cb, path, body)` met `RestCallback`-subclass.
8. **Route-sync**: endpoints in `LLMBridge.c` moeten matchen met `main.py` (`@app.get/post`). Known gaps: `/waypoint` ontbreekt in main.py; `/status` is GET in main.py maar POST in LLMBridge (fix = F1.3).
9. **Poort-sync**: bridge draait op **5001** (`config.json`, bats, LLMBridge default URL).
10. **Geen secrets committen.** `config.json` (met API key) is gitignored; commit alleen `config.example.json`.

## Available agents (Copilot custom)
- Geen `.github/agents/` of `.github/chatmodes/` aanwezig (stand 2026-08-07).

## Skills (detail-docs — lees ze bij werk aan dat gebied)
- Reforger mod-structuur/laden/GUIDs → `@docs/skills/arma-reforger-modding.md`
- Enforce script-taalregels + REST-API → `@docs/skills/enforce-script.md`
- Debug-workflow (console.log, test-cyclus) → `@docs/skills/reforger-debugging.md`

## Status & roadmap
- ✅ F0/F1.1: mod laadt in game, scripts compileren, game bereikt hoofdmenu (geverifieerd via console.log)
- 🔲 F1.2: component wiring — `modded class SCR_BaseGameMode` die `LLMBridge` instantieert + `Update()` via `GetGame().GetCallqueue().CallLater()`. Daarna pas `[LLMBridge]`-regels in-game
- 🔲 F1.3: route-sync game↔bridge (`/waypoint`, `/status`), e2e JSON-validatie
- Volledige planning: `PROJECT_PLAN.md` (NL). Launch-diagnose: `MOD_SETUP.md`.

## References
- `MOD_SETUP.md` — geverifieerde fix + volledige diagnose van de launch-errors
- `PROJECT_PLAN.md` — architectuur & fases
- BI-wiki: `Arma_Reforger:Startup_Parameters`, `:Mod_Project_Setup`, `:REST_API_Usage` (community.bistudio.com)
- SampleMods referentie: `docs/` (GITIGNORED — zelf ophalen: github.com/BohemiaInteractive/Arma-Reforger-Samples)

## Maintenance
- Dit bestand = source of truth. `CLAUDE.md` en `.goosehints` zijn sync-kopieën (Windows: geen symlinks).
- Na wijziging: `scripts\sync-agent-docs.bat` draaien. Pre-commit hook (`core.hooksPath=.githooks`) blokkeert drift.
- Code/comments: Engels. Docs mogen NL. Commit-berichten: kort, feature-gescoped.
