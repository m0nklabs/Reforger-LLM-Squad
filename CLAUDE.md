# AGENTS.md — Reforger-LLM-Squad

> Canonical AI-agent context voor deze repo. LEES DIT EERST.
> Claude Code: `CLAUDE.md` (sync-copy). Goose: `.goosehints` (sync-copy). Copilot: `.github/copilot-instructions.md`.
> Dit bestand = source of truth. Na wijziging: `scripts\sync-agent-docs.bat` draaien.

## ⛔ STOP — 3 fatale valkuilen (lees vóór je iets doet)

Deze fouten kostten al een volledige debug-sessie (2026-08-07). Maak ze niet opnieuw:

1. **`-mod=` bestaat NIET in Arma Reforger** (dat is Arma 3/DayZ). De engine negeert hem ZONDER waarschuwing. Correct: `-addonsDir <pad> -addons <GUID>`.
2. **Start de game ALTIJD met working directory = game-dir.** Anders vindt de engine `./addons` niet → `Can't find '58D0FB3206B6F859' game addon!` (= de BASE GAME ontbreekt, NIET jouw mod) → Engine Initialization Error. `launch_reforger.bat` doet dit correct (`start /d`).
3. **GUID `58D0FB3206B6F859` = de base game** (`addons\data\ArmaReforger.gproj`). Onze mod-GUID = `7E5A1C9B3D8F2406`. Nooit verwisselen of hergebruiken (pre-commit hook bewaakt dit).

⚠️ Bij tegenstrijdigheid met oudere docs wint DIT bestand (+ `MOD_SETUP.md`). `PROJECT_PLAN.md` is gecorrigeerd maar blijft een plandoc.

## Verplichte werkwijze — doen, niet zelf bedenken

| Taak | Exacte actie |
|---|---|
| Game starten met mod | `taskkill /F /IM ArmaReforgerSteam.exe` → `launch_reforger.bat` |
| Resultaat verifiëren | ~50s na start: `powershell -NoProfile -File scripts\check_latest_log.ps1` |
| "Klaar" claimen | ALLEEN als dat script `OK` rapporteert |
| Game-scripts schrijven | EERST `@docs/skills/enforce-script.md` lezen; alleen patronen daaruit gebruiken |
| AGENTS.md wijzigen | daarna `scripts\sync-agent-docs.bat` draaien vóór commit |

NOOIT: eigen launch-commando's verzinnen · GUIDs hergebruiken · `git add -f` op gitignored files · `config.json` committen · "fixed" claimen zonder log-bewijs.

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

## Bestaat NIET in Reforger/Enforce (anti-hallucinatie-lijst)
Verzin deze nooit — ze zijn allemaal al een keer foutgegaan:
- CLI: `-mod`, `-mod=`, `@modmap`
- Enforce: `modclass`, geneste classes (class-in-class), `ref RestContext`, `World.GetGameTime()`
- REST: `new RestContext()`, `SetURL()`, `SetMethod(RestMethod.*)`, `SetBody()`, `Start()`
  → juist: `GetGame().GetRestApi().GetContext(url)` + `GET(cb, path)` / `POST(cb, path, body)` + `RestCallback` (zie `@docs/skills/enforce-script.md` §3)
- Addon-metadata: `addon.json`, `gproj.conf` → juist: `addon.gproj`

## Critical rules (overige, hard-won)
1. **Test = empirisch, altijd**: kill → `launch_reforger.bat` → ~50s → `check_latest_log.ps1`. Crash-signatuur: log ≈1145 bytes. `SCRIPT (E)` in base-game `.c` files ná jouw file = cascade-ruis; fix eerst JOUW eerste error.
2. **Route-sync**: endpoints in `LLMBridge.c` moeten matchen met `main.py` (`@app.get/post`). Known gaps: `/waypoint` ontbreekt in main.py; `/status` is GET in main.py maar POST in LLMBridge (fix = F1.3).
3. **Poort-sync**: bridge draait op **5001** (`config.json`, bats, LLMBridge default URL).
4. **Geen secrets committen.** `config.json` (API key) is gitignored + pre-commit geblokkeerd; commit alleen `config.example.json`.
5. Wijzig nooit de GUID in `addon.gproj` (pre-commit hook blokkeert dit).

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
- `PROJECT_PLAN.md` — architectuur & fases (gecorrigeerd 2026-08-07; bij twijfel wint AGENTS.md)
- BI-wiki: `Arma_Reforger:Startup_Parameters`, `:Mod_Project_Setup`, `:REST_API_Usage` (community.bistudio.com)
- SampleMods referentie: `docs/` (GITIGNORED — zelf ophalen: github.com/BohemiaInteractive/Arma-Reforger-Samples)

## Maintenance
- Dit bestand = source of truth. `CLAUDE.md` en `.goosehints` zijn sync-kopieën (Windows: geen symlinks).
- Na wijziging: `scripts\sync-agent-docs.bat` draaien. Pre-commit hook (`core.hooksPath=.githooks`) blokkeert drift, secrets en GUID-wijzigingen.
- Code/comments: Engels. Docs mogen NL. Commit-berichten: kort, feature-gescoped.
