# AGENTS.md — Reforger-LLM-Squad

> Canonical AI-agent context for this repo. READ THIS FIRST.
> Claude Code: `CLAUDE.md` (sync copy). Goose: `.goosehints` (sync copy). Copilot: `.github/copilot-instructions.md`.
> This file = source of truth. After editing: run `scripts\sync-agent-docs.bat` before committing.

## ⛔ STOP — 3 fatal pitfalls (read before doing anything)

These mistakes already cost a full debug session (2026-08-07). Do not repeat them:

4. **NEVER publish the mod to BI Workshop via Workbench without running `scripts\sync_mod.ps1` afterwards!**
   Workbench publishing creates a `data.pak` in the Workshop cache
   (`Documents\My Games\ArmaReforger\addons\ReforgerLLMSquadControl_7E5A1C9B3D8F2406\`).
   This `.pak` contains the scripts AT THE TIME OF PUBLISHING — it becomes stale the moment you edit any `.c` file.
   - **DS** compiles loose `.c` files (new code, 5639 files)
   - **Client** downloads the `.pak` (old code, 5637 files)
   - **Result**: CRC mismatch → "script mismatch" → client cannot join
   - **FIX**: After ANY edit to `.c` files, run: `powershell -NoProfile -File scripts\sync_mod.ps1`
   - This script syncs loose `.c` files to BOTH DS local + Workshop cache AND removes stale `.pak` files.
   - **NEVER** delete the Workshop cache directory itself — only remove `.pak` and `.rdb` files from it.

1. **`-mod=` does NOT exist in Arma Reforger** (that is Arma 3/DayZ). The engine ignores it WITHOUT warning. Correct: `-addonsDir <path> -addons <GUID>`.
2. **ALWAYS start the DS with working directory = game dir.** Otherwise the engine cannot find `./addons` → `Can't find '58D0FB3206B6F859' game addon!` (= the BASE GAME is missing, NOT your mod) → Engine Initialization Error. `launch_ds.bat` does this correctly.
3. **GUID `58D0FB3206B6F859` = the base game** (`addons\data\ArmaReforger.gproj`). Our mod GUID = `7E5A1C9B3D8F2406`. Never swap or reuse them (the pre-commit hook guards this).

⚠️ If older docs contradict this file, THIS file wins (together with `MOD_SETUP.md`).

## Mandatory workflow — do this, don't improvise

| Task | Exact action |
|---|---|
| Start bridge | `start_bridge.bat` (port 5001, auto-elevates admin for voice PTT key) |
| Start DS with mod | `taskkill /F /IM ArmaReforgerServer.exe` → `launch_ds.bat` (uses `server.json` + `game.mods[]`, mod from BI Workshop) |
| Connect game client | Launch Reforger normally → Multiplayer → Direct Connect → `127.0.0.1:2001` |
| Verify result | ~50s after DS start: `powershell -NoProfile -File scripts\check_latest_log.ps1` (checks newest console.log) |
| Claiming "done" | ONLY if that script reports `OK` |
| Writing game scripts | FIRST read `@docs/skills/enforce-script.md`; only use patterns from it |
| After editing .c files | Run `powershell -NoProfile -File scripts\sync_mod.ps1` (syncs to DS + Workshop cache, removes .pak) |
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
- **Launchers**: `start_bridge.bat` (bridge, port 5001), `launch_ds.bat` (dedicated server)

## Does NOT exist in Reforger/Enforce (anti-hallucination list)
Never invent these — every single one has already gone wrong once:
- CLI: `-mod`, `-mod=`, `@modmap`
- Enforce: `modclass`, nested classes (class-in-class), `ref RestContext`, `World.GetGameTime()`
- REST: `new RestContext()`, `SetURL()`, `SetMethod(RestMethod.*)`, `SetBody()`, `Start()`
  → correct: `GetGame().GetRestApi().GetContext(url)` + `GET(cb, path)` / `POST(cb, path, body)` + `RestCallback` (see `@docs/skills/enforce-script.md` §3)
- Addon metadata: `addon.json`, `gproj.conf` → correct: `addon.gproj`

## Critical rules (misc, hard-won)
1. **Testing is empirical, always**: kill → `launch_ds.bat`= → ~55s → `check_latest_log.ps1`. Crash signature: log ≈1145 bytes. `SCRIPT (E)` in base-game `.c` files AFTER your file = cascade noise; fix YOUR first error first.
2. **Route sync**: endpoints in `LLMBridge.c` must match `main.py` — all 5 routes synced (F1.3 done). Game sends via GET `?data=<json>` (POST body doesn't transmit in Enforce). Endpoints: `/health`, `/sitrep`, `/command`, `/status`, `/waypoint`.
3. **Port sync**: bridge runs on **5001** (config.json, bats, LLMBridge default URL).
4. **Never commit secrets.** `config.json` (API key) is gitignored + pre-commit blocked; only commit `config.example.json`. Docs must never contain the API key.
5. Never change the GUID in `addon.gproj` (pre-commit hook blocks this).
6. **Dedicated Server (DS) — primary and only dev workflow**: The DS (`ArmaReforgerServer.exe`) loads mods published to the BI Workshop. **Working solution:**
   - **`game.mods[]` with the addon GUID** = the `modId` IS the 16-char hex GUID from `addon.gproj` (NOT a Steam numeric ID). Reforger uses BI's own Workshop, not Steam's `publishedfileid`.
   - **DS workflow**: starts vanilla (5633 files) → downloads mod from BI Workshop → reloads with mod (5637 files) → scripts compile + execute → server listens (RPL:2001, RCON:19999).
   - **Prerequisite**: mod MUST be published to BI Workshop (even as unlisted) via Workbench. Before publishing, `game.mods[]` fails with "Addon was not found on workshop".
   - `-config` + `-addons` = **REJECTED** by hard DS check ("config cannot be used together with addons!"). Even with `-addonsDir`. BI wiki is outdated for build 190965.
   - `-world` + `-addons` + `-addonsDir` = mod compiles (5637 files) but DS hangs on "Attempting online Game Config" (no server config).
   - Packed `.pak` + `resourceDatabase.rdb` in DS addons folder = "Available" but NOT "Loaded" (DS only loads core+data as base addons).
   - **Correct scenarioId**: `{ECC61978EDCC2B5A}Missions/23_Campaign.conf` (found via game client log: `PlayGameConfig`)
   - DS ports: RPL=2001, RCON=19999, A2S=17777. Full docs: `docs/dedicated-server-setup.md`.
   - **Workbench publishing**: `ArmaReforgerWorkbenchSteamDiag.exe` in `Q:\SteamLibrary\steamapps\common\Arma Reforger Tools\Workbench\`. Output: `.pak` + `resourceDatabase.rdb` + `manifest.json` in `%LOCALAPPDATA%\Temp\Arma Reforger Workbench\Publishing\<GUID>\`.


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

27. **F3.3: Stavka Feedback Loop (2026-08-10)**: OPFOR strength reported to bridge via query param GET /stavka?opfor=N. Bridge includes OPFOR count in fingerprint (count changes trigger new LLM calls). LLM prompt includes current OPFOR strength and adapts strategy: 0=spawn aggressive, 5=HOLD+reinforce from flank, 8=HOLD (adequate). Game casualty detection every 10s via CountAliveOPFOR() - if count drops, triggers immediate poll. Verified: LLM adapts strategy based on OPFOR strength, 0 crashes.

28. **Phase 2: Voice Pipeline (2026-08-11)**: `faster-whisper` + `sounddevice` + `keyboard` packages. VoiceHandler class in `voice_handler.py` — PTT key listener (global hotkey, background thread), audio capture at 16kHz mono, Whisper STT transcription with VAD filter. On PTT release: transcribe -> call_llm() -> queue result in `pending_orders[]` (game picks up via /orders poll). Config: `voice.enabled`, `voice.ptt_key` (F24), `voice.whisper_model` (tiny/small/medium), `voice.whisper_device` (cpu), `voice.whisper_compute_type` (int8). `keyboard` library requires admin on Windows — `start_bridge.bat` auto-elevates via `powershell Start-Process -Verb RunAs`.
29. **ChimeraWorld uses CastFrom(), NOT Cast() (2026-08-11, F3.5)**: `ChimeraWorld.Cast()` produces "Cast not supported on type 'ChimeraWorld'". The correct API is `ChimeraWorld.CastFrom(GetGame().GetWorld())` (verified via Doxygen). `ChimeraWorld` has a static `CastFrom(BaseWorld world)` method, NOT the inherited `.Cast()` pattern used by `SCR_AIGroup.Cast()` etc. This is because `ChimeraWorld` is a sealed/engine class. Once you have `ChimeraWorld`, use `world.GetTimeAndWeatherManager()` to access `TimeAndWeatherManagerEntity` for time, weather, day/night.

30. **Enforce Script += does not auto-convert int to string (2026-08-11, F3.5)**: `string str = "" + int;` works (auto-conversion in `+`), but `str += int;` fails with "Incompatible parameter". Fix: `str += "" + int;`. The `+=` operator only accepts string parameters, while `+` auto-converts primitives to string. Also, `int.ToString()` is NOT a valid method call (produces "Broken expression"). Always use direct string concatenation: `"" + value` instead of `value.ToString()`.
31. **DS is the dev workflow (2026-08-11)**: The dedicated server (`ArmaReforgerServer.exe`) with `-config server.json` + `game.mods[]`. The DS downloads the mod from BI Workshop, compiles scripts, and hosts the game. The game client connects via Multiplayer -> Direct Connect -> `127.0.0.1:2001`. DS logs go to the same path as game client logs: `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\`. The `check_latest_log.ps1` script works for both. Key difference: the DS loads MainMenuWorld first, then auto-loads the scenario from `server.json`'s `scenarioId`. Scripts execute after the scenario loads (~10s after start).

32. **RPL authority required for entity spawning on DS (2026-08-11, INVESTIGATING)**: On the DS, `SpawnEntityPrefab()` and `SpawnEntityPrefabEx()` calls from StavkaController fail with `NETWORK (E): Attempt to spawn a replicated prefab ... blocked. Allowed server-side only!`. This happens even though the DS IS the server. The DS connects to BI's backend as an RPL "client" for lobby services, which may cause the game logic to run in a non-authoritative context. The StavkaController and AutoSquadManager entity spawning code needs an RPL authority guard. LLMBridge (REST calls) and SITREPs work fine on DS without authority. The offset fix confirmed: LLM now returns relative offsets `[0,0]` instead of absolute coords, and `SCR_AIWorld.GetBLUFORPosition()` correctly finds player position on DS.

31. **DS is primary dev workflow (2026-08-11)**: Dedicated server with -config server.json + game.mods[]. Game client connects via Direct Connect 127.0.0.1:2001. DS logs to same path as game client logs.

32. **RPL authority for entity spawning on DS (2026-08-11)**: SpawnEntityPrefab on DS may fail with NETWORK (E) blocked. Always check Replication.IsServer() before spawning. LLMBridge REST calls work fine without authority.

33. **Workshop cache overrides DS local addons (2026-08-11, CRITICAL)**: DS downloads mod from BI Workshop and caches it in Documents/My Games/ArmaReforger/addons/ReforgerLLMSquadControl_7E5A1C9B3D8F2406/. This OVERRIDES the DS local addons dir. You MUST sync .c files to BOTH locations or DS compiles old code. #1 cause of phantom compile errors.

34. **AutoSquad retry + dynamic group lookup (2026-08-11)**: On DS, players spawn BEFORE joining a group. AutoSquad fires 5s after spawn, finds no group. Fix: retry every 10s for 3min + LLMBridge.FindPlayerGroup() dynamically looks up group each SITREP via SCR_PlayerControllerGroupComponent.GetPlayersGroup().

35. **QueryEntitiesBySphere needs callback function (2026-08-11, F4)**: QueryEntitiesBySphere(pos, radius, array) does NOT work. It expects a callback function. Right: define module-level bool QueryEntityCallback(IEntity ent) and call QueryEntitiesBySphere(pos, 60, QueryEntityCallback).

36. **EGetOutType enum not publicly documented (2026-08-11, F4)**: EGetOutType.ALL, .GETOUT, .NORMAL all fail. Workaround: use AskOwnerToGetOutFromVehicle() instead of GetOutVehicle(). Vanilla commanding system (radial menu) handles vehicle control natively.
37. **ChimeraCharacterController NOT available as script type (2026-08-11, F6)**: Neither `ChimeraCharacterController` nor `SCR_CharacterController` can be used with `Cast()` or `FindComponent()` in Enforce Script (build 190965). Both produce "Unknown type" compile errors. This is likely because character controllers are engine-internal sealed classes not exposed to the script type system. Avoid `GetLifeState()`, `IsUnconscious()`, `IsDead()` on character controllers. Future: investigate `DamageManagerComponent` or `SCR_DamageManagerComponent` for health state detection.
38. **F5: Battle Memory (2026-08-11)**: Bridge maintains a rolling `battle_log` (last 15 events) in `app_state`. Events logged on every SITREP: ORDER (LLM action != HOLD), CONTACT (enemies detected), CRITICAL (leader downed), RECOVERY (leader back up). `get_battle_memory(max_events=8)` returns formatted event list included in `call_llm()` system prompt and `generate_ai_thoughts()` (3 events). LLM now has context of what happened in previous turns. Verified: battle_log populated with ENGAGE orders and enemy contacts. Events persist across SITREPs (not cleared on dedup skip).
39. **F6: Medic Rescue (2026-08-11)**: `leader_state` field added to SITREP JSON (alive/downed/dead). `GetPlayerLifeState()` in LLMBridge.c checks player entity (currently defaults to "alive" — see rule 37). Bridge tracks `last_leader_state` — state change triggers new LLM call (in fingerprint). `MEDIC` added to `ISSUE_ORDER_FUNCTION` enum. On MEDIC action: game creates Follow waypoint at leader position (squad runs to rescue). System prompt instructs LLM: "If LEADER STATUS shows DOWNED, prioritize MEDIC action". Live orders also support `medic` command via /orders.
40. **Individual AI Soldier Memory (2026-08-11, DEVELOPMENT ROADMAP)**: Each AI squad member is a unique personality with their own memory file (`python_bridge/ai_soldiers/{name}.json`). NOT shared/global memory. Each soldier tracks: name, personality, birth_date, personal event log, opinions, mood, relationships, status (alive/dead). When a soldier dies in-game: file is marked `status=dead, death_date=<timestamp>` and retained for 7 days for debugging, then archived to `ai_soldiers/graveyard/`. Thoughts are generated based on personal history, not just current SITREP. This makes each soldier feel like a real person who remembers what they've been through.
41. **Eureka Workflow (2026-08-11, MANDATORY)**: At every eureka moment (breakthrough discovery, major bug fix, new feature working, important lesson learned):
    1. Update `AGENTS.md` with the new knowledge (rule, status entry, or both)
    2. Run `scripts\sync-agent-docs.bat` to sync to CLAUDE.md + .goosehints
    3. Commit with descriptive message
    4. Push to GitHub: `git push origin main`
    This ensures knowledge is never lost and the team always has the latest context.
42. **AGENTS.md Maintenance (2026-08-11)**: AGENTS.md is the single source of truth. Keep it current:
    - After every feature implementation → update Status & roadmap
    - After every hard-won lesson → add a rule
    - After every debugging session → update relevant rules
    - Remove obsolete info when patterns are replaced
    - Run `scripts\sync-agent-docs.bat` BEFORE committing
    - Push to GitHub after significant updates

## Available agents (Copilot custom)
- No `.github/agents/` or `.github/chatmodes/` present (as of 2026-08-07).

## Skills (detail docs — read when working in that area)
- Reforger mod structure/loading/GUIDs → `@docs/skills/arma-reforger-modding.md`
- Enforce script language rules + REST API → `@docs/skills/enforce-script.md`
- Debug workflow (console.log, test cycle) → `@docs/skills/reforger-debugging.md`

## Status & roadmap
- ✅ F0/F1.1: mod loads in game, scripts compile, game reaches main menu (verified via console.log)
- ✅ F1.2a: AutoSquadManager.c compiles, modded classes work in-game (AddedAIAgent, OnControlledEntityChanged)

- ✅ F1.2b: end-to-end test PASSED — player spawns, AutoSquad finds group, sets player as leader, spawns squad. All verified via console.log (2026-08-09):
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

- ✅ **DS WITH MOD WORKING (2026-08-09 21:28)**:
  - Mod published to BI Workshop via Workbench (unlisted)
  - `game.mods[]` with GUID `7E5A1C9B3D8F2406` = modId IS the addon GUID (NOT Steam numeric ID)
  - DS downloads mod from BI Workshop → 5637 files → scripts compile + execute
  - `[LLMGameMode] OnGameStart` + `[LLMBridge] Bridge healthy` + SITREP sent on DS!

  - RPL:2001, RCON:19999, A2S:17777 all active with mod loaded
- F3.1 (2026-08-10): Stavka OPFOR Strategic AI - LLM decides OPFOR strategy every 60s. Bridge /stavka endpoint -> StavkaController.c -> spawns USSR Rifleman soldiers. Verified on DS.
- F3.2 (2026-08-10): OPFOR Waypoint Assignment - soldiers grouped into AI groups, formation Wedge, Move waypoint toward BLUFOR. OPFOR cap (MAX_OPFOR=10) via CountAliveOPFOR(). Zero SCRIPT(E), verified on DS with 2 cycles.
 - F3.3 (2026-08-10): Feedback Loop - OPFOR count sent to bridge (GET ?opfor=N), LLM adapts strategy (spawn when weak, hold when sufficient), casualty detection triggers early polls
- Phase 2 (2026-08-11): Voice Pipeline (Whisper STT) - voice_handler.py with PTT key listener, faster-whisper transcription, transcription -> LLM -> pending_orders queue. GET /voice endpoint for status. Model: tiny (2.8s load). Auto-elevate admin in start_bridge.bat.
- F3.5 (2026-08-11): Environment Scanning - ScanEnvironment() in LLMBridge.c reports time/day/night + terrain elevation. Uses ChimeraWorld.CastFrom(), TimeAndWeatherManagerEntity (GetTime, IsSunSet). Bridge receives 'environment' field in SITREP, includes in LLM prompt, adds to fingerprint (time changes trigger new calls). 8/8 tests pass.
- Phase 3 (2026-08-11): TTS Squad Feedback - edge-tts (primary, 10 voices) + pyttsx3 (offline fallback). tts_handler.py with TTSHandler class. Bridge speaks voice_reply from SITREP/command/voice endpoints via background thread. /tts endpoint for status. Rate-limited (2s min interval), dedup (no repeat). 9/9 tests pass.
- F4 (2026-08-11): Vehicle mount/dismount commands. MOUNT/DISMOUNT in LLM enum, AutoSquadManager.MountNearestVehicle() + DismountVehicle(). Vanilla radial menu also works natively.
- F4 (2026-08-11): Vehicle mount/dismount commands. MOUNT/DISMOUNT in LLM enum, AutoSquadManager.MountNearestVehicle() + DismountVehicle(). Also fixed Stavka offset bug: BLUFOR position now found via SCR_AIWorld.GetBLUFORPosition() (was returning <0,0,0>), LLM prompt stripped of absolute coords (was returning absolute coords as offset), offset clamped to 500m max.
- F5 (2026-08-11): Battle Memory — bridge maintains rolling battle_log (15 events), included in LLM prompt. LLM now remembers previous orders, enemy contacts, and critical events. Verified on DS: battle_log populated, leader_state in fingerprint.
- F6 (2026-08-11): Medic Rescue — leader_state (alive/downed/dead) in SITREP JSON + fingerprint. MEDIC action in LLM enum: squad runs to downed leader with Follow waypoint. Downed detection TODO (rule 37: ChimeraCharacterController not available as script type). Framework ready for when correct API is found.
- **F7 (2026-08-11, ROADMAP): Individual AI Soldier Memory** — Each AI soldier gets personal memory file (`ai_soldiers/{name}.json`) with: name, personality, birth_date, personal event log, opinions, mood, relationships, alive/dead status. NOT shared memory. Events logged per-soldier (contact, casualties, order changes). Thoughts generated from personal history. Death = retain file 7 days for debugging, then archive to `graveyard/`. Makes soldiers feel like real people who remember their experiences.
- **F8 (2026-08-11, VISION/ROADMAP): AI Soldiers as Autonomous Agents** — Evolution of F7. Each AI soldier is not just a "thought generator" but an autonomous LLM agent with:
  - **Identity System Prompt**: Each soldier gets a dedicated system prompt establishing their identity:
    - Name, faction (US/USSR), rank (PFC, Sergeant, etc.), role (Rifleman, AR, Medic)
    - Chain of command: who is their CO (the player), who are their squadmates
    - Expectations: what is expected of them in their role and current mission
  - **Backstory**: Personal history used in the system prompt (age, origin, time in theater, prior deployments, personality traits). Could come from game data or generated at spawn. Makes each soldier unique — a rookie fresh from training sounds different from a veteran on their third deployment.
  - **Available Tools**: The soldier LLM can call tools to interact with the game world, not just generate text:
    - `report_contact(direction, distance, count)` — report enemy sighting to squad
    - `report_clear()` — report area is clear
    - `request_orders()` — ask CO for new orders
    - `report_status(health, ammo)` — report own condition
    - `call_medic(target)` — request medical help for a squadmate
    - `suggest_tactic(formation, direction)` — suggest a tactical change
  - **Agent, not commentator**: The soldier observes → decides → acts. Thoughts are just one output; tool calls are the other. A soldier who spots an enemy doesn't just think "I see someone" — they call `report_contact()` which triggers game logic.
  - **Per-soldier conversation history**: Each soldier maintains their own LLM conversation history (messages array), not just a flat event log. This allows the LLM to reference prior context naturally.
  - **Game backstory integration**: Arma Reforger may provide backstory/lore for spawned character entities. If available, this should be used in the soldier's system prompt to give them depth.
- **Eureka Workflow (2026-08-11, MANDATORY)**: At every breakthrough/fix/discovery: update AGENTS.md → sync docs → commit → push to GitHub. Knowledge is never lost.
- **Event-driven thoughts (2026-08-11)**: Replaced 30s thought timer with event detection. Thoughts trigger on: contact (enemy detected), clear (enemies eliminated), order_change (LLM order changed), casualty (squad member lost), idle (60s fallback). 15s cooldown between thought polls. Event context added to LLM prompt so thoughts are reactive, not scheduled.
- **Dynamic faction (2026-08-11)**: Squad soldier prefab + OPFOR faction now dynamic based on player faction. US player → US squad + USSR OPFOR. USSR player → USSR squad + US OPFOR. Faction set via FactionManager.GetPlayerFaction() per-soldier.
- **Stavka disabled (2026-08-11)**: Stavka OPFOR spawning disabled — vanilla 23_Campaign already has OPFOR/FIA forces. Stavka was spawning additional OPFOR on top of vanilla, causing enemies near spawn. Controller kept alive for future use.
- Launch diagnosis: `MOD_SETUP.md`.

## References
- `MOD_SETUP.md` — verified fix + full diagnosis of the launch errors

- BI wiki: `Arma_Reforger:Startup_Parameters`, `:Mod_Project_Setup`, `:REST_API_Usage` (community.bistudio.com)
- SampleMods reference: `docs/` (GITIGNORED — fetch yourself: github.com/BohemiaInteractive/Arma-Reforger-Samples)

## Maintenance
- This file = source of truth. `CLAUDE.md` and `.goosehints` are sync copies (Windows: no symlinks).
- After editing: run `scripts\sync-agent-docs.bat`. The pre-commit hook (`core.hooksPath=.githooks`) blocks drift, secrets and GUID changes.
- Language: **English everywhere** — code, comments, docs, commit messages. Commits: short, feature-scoped.
