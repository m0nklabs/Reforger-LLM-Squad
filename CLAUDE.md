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
2. **Route sync**: endpoints in `LLMBridge.c` must match `main.py` — all 5 routes synced (F1.3 done). Game sends via GET `?data=<json>` (POST body doesn't transmit in Enforce). Endpoints: `/health`, `/sitrep`, `/command`, `/status`, `/waypoint`.
3. **Port sync**: bridge runs on **5001** (config.json, bats, LLMBridge default URL).
4. **Never commit secrets.** `config.json` (API key) is gitignored + pre-commit blocked; only commit `config.example.json`. Docs must never contain the API key.
5. Never change the GUID in `addon.gproj` (pre-commit hook blocks this).
6. **Dedicated server vs listen server (2026-08-09, BREAKTHROUGH)**: The DS (`ArmaReforgerServer.exe`) CAN load mods published to the BI Workshop. **Final working solution:**
   - **`game.mods[]` with the addon GUID** = the `modId` IS the 16-char hex GUID from `addon.gproj` (NOT a Steam numeric ID). Reforger uses BI's own Workshop, not Steam's `publishedfileid`.
   - **DS workflow**: starts vanilla (5633 files) → downloads mod from BI Workshop → reloads with mod (5637 files) → scripts compile + execute → server listens (RPL:2001, RCON:19999).
   - **Prerequisite**: mod MUST be published to BI Workshop (even as unlisted) via Workbench. Before publishing, `game.mods[]` fails with "Addon was not found on workshop".
   - `-config` + `-addons` = **REJECTED** by hard DS check ("config cannot be used together with addons!"). Even with `-addonsDir`. BI wiki is outdated for build 190965.
   - `-world` + `-addons` + `-addonsDir` = mod compiles (5637 files) but DS hangs on "Attempting online Game Config" (no server config).
   - Packed `.pak` + `resourceDatabase.rdb` in DS addons folder = "Available" but NOT "Loaded" (DS only loads core+data as base addons).
   - **Correct scenarioId**: `{ECC61978EDCC2B5A}Missions/23_Campaign.conf` (found via game client log: `PlayGameConfig`)
   - DS ports: RPL=2001, RCON=19999, A2S=17777. Full docs: `docs/dedicated-server-setup.md`.
   - **Workbench publishing**: `ArmaReforgerWorkbenchSteamDiag.exe` in `Q:\SteamLibrary\steamapps\common\Arma Reforger Tools\Workbench\`. Output: `.pak` + `resourceDatabase.rdb` + `manifest.json` in `%LOCALAPPDATA%\Temp\Arma Reforger Workbench\Publishing\<GUID>\`.
7. **Play (offline) vs Host (multiplayer) — CRITICAL (2026-08-09)**: When you click **Host** in the scenario menu, the game DESTROYS the first instance and creates a NEW one — WITHOUT loading local mods (5633 = vanilla). When you click **Play** (offline/single-player), the game stays in the SAME instance (5637 = mod loaded). **For mod testing, ALWAYS use Play, not Host.** The modded classes only execute in the Play (offline) path.
8. **Packed vs unpacked mods (2026-08-09)**: Unpacked mods (loose `.c` files + `addon.gproj`) work correctly for script execution. Packed `.pak` files are recognized (`(packed)` in log) but **do not load modded classes at runtime** — the scripts compile but `Print()` output never appears. Use unpacked for development; packed only for workshop publishing.
9. **Cached workshop mods (2026-08-09)**: If the user previously joined a community server, 100+ workshop mods may be cached in `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\`. These cause `ADDON_LOAD_ERROR` when starting a scenario. Fix: move them to `addons_disabled/` subfolder. Our mod in `-addonsDir` is separate and unaffected.
10. **`SCR_AIGroup.IsFull()` does NOT exist** (2026-08-09). Use `GetPlayerAndAgentCount()` vs `GetMaxMembers()` instead. Verified via Doxygen member list.
11. **REST callback GC (2026-08-09)**: Inline `new RestCallback(...)` passed to `GET()`/`POST()` is garbage-collected before the async HTTP response arrives. Callbacks NEVER fire. Fix: store in `ref array<ref MyCallback> m_aActiveCallbacks` to keep alive. Both `SetOnSuccess` (modern) and `OnSuccess` (deprecated override) fire correctly once the callback survives GC.
12. **POST body never transmits (2026-08-09)**: `RestContext.POST(cb, path, body)` sends the HTTP request, but the body parameter arrives empty at the server (`Content-Length: 0`). Fix: send data via GET query param (`/sitrep?data=<urlencoded_json>`). Enforce has no built-in URL encoder — write your own (see `LLMBridge.UrlEncode()`).
13. **Confirmed US soldier prefab (2026-08-09)**: Found in vanilla SDK source code, NOT invented:
    - `{5B1996C05B1E51A4}Prefabs/Characters/Factions/BLUFOR/US_Army/Character_US_AR.et` (Automatic Rifleman, armed)
    - `{2F912ED6E399FF47}Prefabs/Characters/Factions/BLUFOR/US_Army/Character_US_Unarmed.et` (unarmed)
    - Source: `SCR_AutotestCommonFixture.c`, `SCR_CareerProfileHUD.c` in vanilla SDK.
14. **SpawnUnits() does NOT spawn AI (2026-08-09)**: `SCR_AIGroup.SpawnUnits()` uses `m_aUnitPrefabSlots` (editor-set array) to determine what to spawn. `SetNumberOfMembersToSpawn()` only sets a cap (`m_iMaxUnitsToSpawn`), NOT the prefab list. Dynamically found groups have empty `m_aUnitPrefabSlots`. Fix: manual spawn via `SpawnEntityPrefabEx(prefabName, true, world, params)` + `AIControlComponent.GetControlAIAgent()` (NOT `GetAIAgent()`) + `ActivateAI()` + `group.AddAgent(agent)`.
15. **AIFormationComponent required for squad movement (2026-08-09)**: Without `AIFormationComponent.SetFormation("Column")` (or "Wedge"/"Line"/"StaggeredColumn"), spawned AI soldiers stand still and do not follow the leader. Set formation after spawning:
    ```c
    AIFormationComponent fc = AIFormationComponent.Cast(grp.FindComponent(AIFormationComponent));
    fc.SetFormation("Column");
    ```
16. **DS scenarioId (2026-08-09)**: The scenario ID for the DS config is NOT the `.ent` world file. It is: `{ECC61978EDCC2B5A}Missions/23_Campaign.conf` (found via game client log `PlayGameConfig`).
17. **Live orders system (2026-08-09)**: Game polls `GET /orders` every 2s. Bridge queues commands via `POST /orders`. Commands: `spawn`, `hold`, `move` (with `[dx,dz]` offset array), `status`, `despawn`, `formation`, `follow`. Enables debugging without game restart. Offset must be JSON array `[100,50]` not string `"100,50"`.
18. **Master/Slave group architecture (2026-08-09, CRITICAL for MP)**: Arma Reforger uses a **master group** (player-facing, shown in UI) and a **slave group** (AI-facing, manages AI agents) architecture. The commanding system (`SCR_CommandingManagerComponent`) ALWAYS accesses AI through `masterGroup.GetSlave()`. Adding AI directly to the master group via `AddAgent()` does NOT work in multiplayer because:
    - `AddAgent()` is a `proto external` C++ call with no RPL broadcast
    - `AddAgentFromControlledEntity()` calls `OnGroupMemberStateChange()` which broadcasts via `Rpc(RPC_DoOnGroupMemberStateChange)` to clients
    - Without this broadcast, the client never sees the AI in its group UI and cannot command them
    - Fix: create slave group via `EnsureSlaveGroup()`, then `slaveGroup.AddAgentFromControlledEntity(aiEnt)`
    - Slave group prefab: `{04D3B38E23F51754}Prefabs/AI/Groups/Slave_Group.et` (from `SCR_CommandingManagerComponent`)
    - `GetAgents()` returns empty array on client when agents are remotely controlled (engine limitation); use `GetServerAgentsCount()` instead
19. **DS server.json publicAddress (2026-08-09)**: Set `publicAddress` and `publicPort` in server.json to make the server discoverable on LAN. Without these, the server registers with its public IP (not LAN IP) and may not appear in the server browser.
20. **DS mod loading final solution (2026-08-09, BREAKTHROUGH)**: Mod MUST be published to BI Workshop (even as unlisted). `game.mods[]` with `modId = addon GUID` (16-char hex from `addon.gproj`, NOT Steam numeric ID). DS downloads mod from BI Workshop on startup → 5637 files → scripts compile + execute. Workbench publishing: `ArmaReforgerWorkbenchSteamDiag.exe` → output in `%LOCALAPPDATA%\Temp\Arma Reforger Workbench\Publishing\<GUID>\`.
21. **SCR_AICombatComponent crash with manually spawned AI (2026-08-09)**: `GetCombatMode()` calls `myGroup.GetGroupUtilityComponent().GetCombatModeActual()`. If AI is activated before the slave group's `SCR_AIGroupUtilityComponent` is initialized, `GetGroupUtilityComponent()` returns null → Virtual Machine Exception (8822 crashes in one session!). Fix: add AI to group FIRST via `AddAgentFromControlledEntity()`, then delay `ActivateAI()` by 500ms via `CallLater` to let group components initialize.
22. **Auto-follow default behavior (2026-08-09)**: After spawning AI, create a Follow waypoint (`{A0509D3C4DD4475E}Prefabs/AI/Waypoints/AIWaypoint_Follow.et`) at the player's position and add it to the slave group. This makes the squad follow the player by default without needing manual orders.
23. **Uvicorn HTTP Upgrade headers (2026-08-10, ROOT CAUSE FIX)**: Reforger's Enforce `RestContext` sends `Connection: Upgrade` headers on normal HTTP REST requests. Uvicorn's HTTP protocol layer (h11/httptools) has TWO warnings: (1) "Unsupported upgrade request." and (2) "No supported WebSocket library detected." 
   - `ws="none"` does NOT fix this — it sets `ws_protocol_class=None`, which triggers warning #2.
   - **Root cause fix**: monkey-patch `H11Protocol._should_upgrade` and `HttpToolsProtocol._should_upgrade` at module level in `main.py` to return `False` silently for non-WebSocket upgrades (only `Upgrade: websocket` passes through). This prevents BOTH warnings. Correct HTTP behavior per RFC 7230 §6.1.
   - Do NOT use `ws="none"` — the websockets library IS installed (v17.0.1), so uvicorn auto-detects it. The monkey-patch handles Reforger's non-WebSocket Upgrade headers.
   - `start_bridge.bat` must use `python main.py` (not `python -m uvicorn main:app`) so all uvicorn parameters (timeout_keep_alive, limit_concurrency) take effect. The monkey-patch works in both modes because it's module-level.
24. **F2.7: Individual AI Brains (2026-08-10)**: Each AI squad member has a personality (AGGRESSIVE, CAUTIOUS, JOKER, VETERAN, ROOKIE, STEADY). Personalities assigned deterministically by name hash (stable across restarts). Bridge generates one thought per member via single LLM call (plain text prompt, not function calling — 3B models can't handle complex JSON schemas). Thoughts are deduplicated (cached when situation unchanged). Game polls `/ai_thought` every 30s, displays via `SCR_ChatComponent.RadioProtocolMessage()`. Key lesson: llama3.2-3b with `response_format={"type": "json_object"}` returns empty content intermittently. Function calling with nested array schemas returns empty arrays. Plain text prompt + string parsing is the only reliable approach for 3B models.
25. **F3.1/F3.2: Stavka OPFOR Strategic AI (2026-08-10)**: LLM-driven OPFOR forces. Bridge `/stavka` endpoint generates strategic orders (JSON: `{"orders":[{"action":"spawn_and_move","count":2,"offset":[300,0],"tactic":"flanking"}]}`, uses `response_format={"type":"json_object"}`, temperature=0.5, dedup via fingerprint). Game's `StavkaController.c` polls every 60s, spawns USSR Rifleman (`{DCB41B3746FDD1BE}Prefabs/Characters/OPFOR/USSR_Army/Character_USSR_Rifleman.et`) into AI groups with `AddAgentFromControlledEntity()` + delayed `ActivateAI(500ms)` (rule 21). OPFOR cap: `MAX_OPFOR=10` via `CountAliveOPFOR()` counting agents across tracked groups. Move waypoint: `{750A8D1695BD6998}Prefabs/AI/Waypoints/AIWaypoint_Move.et` at BLUFOR position. Formation Wedge via `AIFormationComponent.SetFormation("Wedge")`. Verified on DS: zero crashes, zero SCRIPT(E), OPFOR spawn + move + formation all functional.
26. **`ref` arrays with engine classes (2026-08-10)**: In Enforce Script, `ref` (strong reference) is only valid for script-defined classes. Engine classes (like `SCR_AIGroup`, `IEntity`, `AIAgent`) CANNOT use `ref` as element type — compilation error: "Strong ref to 'SCR_AIGroup' class is not allowed". However, the array itself IS a script object and NEEDS `ref` — without it: "Variable is not strong ref (missing 'ref'?)". Correct: `ref array<SCR_AIGroup>`. Wrong: `ref array<ref SCR_AIGroup>` (element ref fails) or `array<SCR_AIGroup>` (missing array ref).

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
- ✅ F1.3: route sync game↔bridge — all 5 endpoints synced (2026-08-09 14:57):
  - Fixed REST callback GC (ref array keeps callbacks alive for async response)
  - Fixed POST body empty (switched to GET ?data=<urlencoded_json>)
  - E2E: game sends SITREP → bridge parses → LLM processes → response callback fires in game
  - `m_bLLMReady = true` (health check callback fires successfully)
- ✅ F2.x: Live orders + AI squad spawn (2026-08-09 20:30):
  - 5 AI soldiers spawn with confirmed prefab `{5B1996C05B1E51A4}Character_US_AR.et`
  - `SpawnEntityPrefabEx` + `GetControlAIAgent()` + `ActivateAI()` + `AddAgent()` pattern
  - `AIFormationComponent.SetFormation("Column")` for squad movement
  - Live orders: spawn, hold, move, status, despawn, formation, follow
  - LLM: qwen3.6-35b-uncensored (switched from llama3)
- ✅ DS investigation (2026-08-09 21:30):
  - DS installed: `Q:\SteamLibrary\steamapps\common\Arma Reforger Server\`
  - Correct scenarioId: `{ECC61978EDCC2B5A}Missions/23_Campaign.conf`
  - Vanilla DS starts: RPL:2001, RCON:19999, A2S:17777
  - `-config` + `-addons` CANNOT be combined (hard DS check)
  - Mod compiles on DS (5637 files) but needs `.pak` or workshop for loading
  - Full docs: `docs/dedicated-server-setup.md`
- ✅ **DS WITH MOD WORKING (2026-08-09 21:28)**:
  - Mod published to BI Workshop via Workbench (unlisted)
  - `game.mods[]` with GUID `7E5A1C9B3D8F2406` = modId IS the addon GUID (NOT Steam numeric ID)
  - DS downloads mod from BI Workshop → 5637 files → scripts compile + execute
  - `[LLMGameMode] OnGameStart` + `[LLMBridge] Bridge healthy` + SITREP sent on DS!

  - RPL:2001, RCON:19999, A2S:17777 all active with mod loaded
- F3.1 (2026-08-10): Stavka OPFOR Strategic AI - LLM decides OPFOR strategy every 60s. Bridge /stavka endpoint -> StavkaController.c -> spawns USSR Rifleman soldiers. Verified on DS.
- F3.2 (2026-08-10): OPFOR Waypoint Assignment - soldiers grouped into AI groups, formation Wedge, Move waypoint toward BLUFOR. OPFOR cap (MAX_OPFOR=10) via CountAliveOPFOR(). Zero SCRIPT(E), verified on DS with 2 cycles.
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
