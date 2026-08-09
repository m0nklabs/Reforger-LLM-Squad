# AGENTS.md — Reforger-LLM-Squad

> Canonical AI-agent context for this repo. READ THIS FIRST.
> Claude Code: `CLAUDE.md` (sync copy). Goose: `.goosehints` (sync copy). Copilot: `.github/copilot-instructions.md`.
> This file = source of truth. After editing: run `scripts\sync-agent-docs.bat` before committing.

## ⛔ STOP — 3 fatal pitfalls (read before doing anything)

These mistakes already cost a full debug session (2026-08-07). Do not repeat them:

1. **`-mod=` does NOT exist in Arma Reforger** (that is Arma 3/DayZ). The engine ignores it WITHOUT warning. Correct: `-addonsDir <path> -addons <GUID>`.
2. **ALWAYS start the game with working directory = game dir.** Otherwise the engine cannot find `./addons` → `Can't find '58D0FB3206B6F859' game addon!` (= the BASE GAME is missing, NOT your mod) → Engine Initialization Error. `launch_reforger.bat` does this correctly (`start /d`).
3. **GUID `58D0FB3206B6F859` = the base game** (`addons\data\ArmaReforger.gproj`). Our mod GUID = `7E5A1C9B3D8F2406`. Never swap or reuse them (the pre-commit hook guards this).

⚠️ If older docs contradict this file, THIS file wins (together with `MOD_SETUP.md`). `PROJECT_PLAN.md` was corrected but remains a planning doc.

## Mandatory workflow — do this, don't improvise

| Task | Exact action |
|---|---|
| Start game with mod | `taskkill /F /IM ArmaReforgerSteam.exe` → `launch_reforger.bat` (listen server: no backend, no workshop needed) |
| Start DS (production only) | Only with published workshop mod (`-config server.json` + `game.mods[]`). DS CANNOT load local mods. |
| Verify result | ~50s after start: `powershell -NoProfile -File scripts\check_latest_log.ps1` |
| Claiming "done" | ONLY if that script reports `OK` |
| Writing game scripts | FIRST read `@docs/skills/enforce-script.md`; only use patterns from it |
| Editing AGENTS.md | run `scripts\sync-agent-docs.bat` before committing |

NEVER: invent your own launch commands · reuse GUIDs · `git add -f` on gitignored files · commit `config.json` · claim "fixed" without log evidence.

## What this project is
LLM-driven squad control for Arma Reforger. An Enforce-script mod in the game talks over
HTTP to a local FastAPI bridge, which forwards requests to an LLM (Ollama-compatible proxy
on the LAN). Phase 1 = REST + squad control (no voice yet).

## Stack
- **Game mod**: Arma Reforger (build 190965), Enforce script (`.c`). Addon = `reforger_mod/addons/ReforgerLLMSquad/` with `addon.gproj` (GameProject format)
- **Bridge**: Python 3.11, FastAPI + uvicorn + pydantic + openai client. Entry: `python_bridge/main.py`. Config: `python_bridge/config.json` (GITIGNORED — copy from `config.example.json`)
- **LLM**: Ollama-compatible proxy `http://192.168.1.35:11434/v1`, model `llama3`
- **Platform**: Windows-only paths. Game dir: `Q:\SteamLibrary\steamapps\common\Arma Reforger`
- **Logs**: `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<timestamp>\console.log`
- **Launchers**: `start_bridge.bat` (bridge, port 5001), `launch_reforger.bat` (game + mod)

## Does NOT exist in Reforger/Enforce (anti-hallucination list)
Never invent these — every single one has already gone wrong once:
- CLI: `-mod`, `-mod=`, `@modmap`
- Enforce: `modclass`, nested classes (class-in-class), `ref RestContext`, `World.GetGameTime()`
- REST: `new RestContext()`, `SetURL()`, `SetMethod(RestMethod.*)`, `SetBody()`, `Start()`
  → correct: `GetGame().GetRestApi().GetContext(url)` + `GET(cb, path)` / `POST(cb, path, body)` + `RestCallback` (see `@docs/skills/enforce-script.md` §3)
- Addon metadata: `addon.json`, `gproj.conf` → correct: `addon.gproj`

## Critical rules (misc, hard-won)
1. **Testing is empirical, always**: kill → `launch_reforger.bat` → ~50s → `check_latest_log.ps1`. Crash signature: log ≈1145 bytes. `SCRIPT (E)` in base-game `.c` files AFTER your file = cascade noise; fix YOUR first error first.
2. **Route sync**: endpoints in `LLMBridge.c` must match `main.py` (`@app.get/post`). Known gaps: `/waypoint` missing in main.py; `/status` is GET in main.py but POST in LLMBridge (fix = F1.3).
3. **Port sync**: bridge runs on **5001** (config.json, bats, LLMBridge default URL).
4. **Never commit secrets.** `config.json` (API key) is gitignored + pre-commit blocked; only commit `config.example.json`. Docs must never contain the API key.
5. Never change the GUID in `addon.gproj` (pre-commit hook blocks this).
6. **Dedicated server vs listen server (2026-08-09)**: The DS (`ArmaReforgerServer.exe`) CANNOT load local unpublished mods — `-config` + `-addons` are mutually exclusive (`DEFAULT (F): -config cannot be used together with addons!`), `game.mods[]` triggers workshop validation (`Addon was not found on workshop`), and `-addons` alone hangs on `BACKEND: Attempting online Game Config`. For development, use the **listen server**: game client (`ArmaReforgerSteam.exe`) with `-addonsDir <path> -addons <GUID>`, then host via in-game menu. No backend validation needed. `-autoStartScenario` works ONLY on DS, not on game client.
7. **Play (offline) vs Host (multiplayer) — CRITICAL (2026-08-09)**: When you click **Host** in the scenario menu, the game DESTROYS the first instance and creates a NEW one — WITHOUT loading local mods (5633 = vanilla). When you click **Play** (offline/single-player), the game stays in the SAME instance (5637 = mod loaded). **For mod testing, ALWAYS use Play, not Host.** The modded classes only execute in the Play (offline) path.
8. **Packed vs unpacked mods (2026-08-09)**: Unpacked mods (loose `.c` files + `addon.gproj`) work correctly for script execution. Packed `.pak` files are recognized (`(packed)` in log) but **do not load modded classes at runtime** — the scripts compile but `Print()` output never appears. Use unpacked for development; packed only for workshop publishing.
9. **Cached workshop mods (2026-08-09)**: If the user previously joined a community server, 100+ workshop mods may be cached in `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\`. These cause `ADDON_LOAD_ERROR` when starting a scenario. Fix: move them to `addons_disabled/` subfolder. Our mod in `-addonsDir` is separate and unaffected.
10. **`SCR_AIGroup.IsFull()` does NOT exist** (2026-08-09). Use `GetPlayerAndAgentCount()` vs `GetMaxMembers()` instead. Verified via Doxygen member list.

## Available agents (Copilot custom)
- No `.github/agents/` or `.github/chatmodes/` present (as of 2026-08-07).

## Skills (detail docs — read when working in that area)
- Reforger mod structure/loading/GUIDs → `@docs/skills/arma-reforger-modding.md`
- Enforce script language rules + REST API → `@docs/skills/enforce-script.md`
- Debug workflow (console.log, test cycle) → `@docs/skills/reforger-debugging.md`

## Status & roadmap
- ✅ F0/F1.1: mod loads in game, scripts compile, game reaches main menu (verified via console.log)
- ✅ F1.2a: AutoSquadManager.c compiles, modded classes work in-game (AddedAIAgent, OnControlledEntityChanged)
- ✅ Dev workflow resolved: listen server (game client) loads local mods without workshop publishing
  - Dedicated server CANNOT: `-config` + `-addons` are mutually exclusive; `-addons` alone hangs on backend; `game.mods[]` triggers workshop validation
  - Game client: `-addonsDir <path> -addons <GUID>` → mod loads, scripts execute, no backend crash
  - **Use Play (offline), NOT Host (multiplayer)** — Host destroys the instance and reloads vanilla (5633 files)
  - **Use unpacked mods** — packed .pak files compile but modded classes don't execute at runtime
- ✅ F1.2b: end-to-end test PASSED — player spawns, AutoSquad finds group, sets player as leader, calls SetNumberOfMembersToSpawn(5) + SpawnUnits(). All verified via console.log (2026-08-09 13:17):
  ```
  [AutoSquad] Player 1 entity changed, scheduling squad spawn (5s delay)
  [AutoSquad] Player faction: US
  [AutoSquad] Found player group via groupComp: SCR_AIGroup
  [AutoSquad] Player 1 set as group leader
  [AutoSquad] SetNumberOfMembersToSpawn(5)
  [AutoSquad] SpawnUnits() called
  [AutoSquad] SUCCESS: Auto-squad complete for player 1
  [LLMGameMode] OnGameStart - Initializing LLM Bridge
  [LLMBridge] LLM Bridge activated, periodic updates started
  ```
- 🔲 F1.3: route sync game↔bridge (`/waypoint`, `/status`), e2e JSON validation
- Full plan: `PROJECT_PLAN.md`. Launch diagnosis: `MOD_SETUP.md`.

## References
- `MOD_SETUP.md` — verified fix + full diagnosis of the launch errors
- `PROJECT_PLAN.md` — architecture & phases (corrected 2026-08-07; AGENTS.md wins when in doubt)
- BI wiki: `Arma_Reforger:Startup_Parameters`, `:Mod_Project_Setup`, `:REST_API_Usage` (community.bistudio.com)
- SampleMods reference: `docs/` (GITIGNORED — fetch yourself: github.com/BohemiaInteractive/Arma-Reforger-Samples)

## Maintenance
- This file = source of truth. `CLAUDE.md` and `.goosehints` are sync copies (Windows: no symlinks).
- After editing: run `scripts\sync-agent-docs.bat`. The pre-commit hook (`core.hooksPath=.githooks`) blocks drift, secrets and GUID changes.
- Language: **English everywhere** — code, comments, docs, commit messages. Commits: short, feature-scoped.
