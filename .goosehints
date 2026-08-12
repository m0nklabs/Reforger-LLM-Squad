# AGENTS.md — Reforger-LLM-Squad

> Canonical AI-agent context for this repo. READ THIS FIRST.
> Claude Code: `CLAUDE.md` (sync copy). Goose: `.goosehints` (sync copy). Copilot: `.github/copilot-instructions.md`.
> This file = source of truth. After editing: run `scripts\sync-agent-docs.bat` before committing.

## STOP — 3 fatal pitfalls (read before doing anything)

1. **NEVER publish the mod to BI Workshop via Workbench without running `scripts\sync_mod.ps1` afterwards!**
   Workbench publishing creates a `data.pak` in the Workshop cache that becomes stale the moment you edit any `.c` file.
   - DS compiles loose `.c` files (new code) → Client downloads the `.pak` (old code) → CRC mismatch → client cannot join
   - **FIX**: After ANY edit to `.c` files, run: `powershell -NoProfile -File scripts\sync_mod.ps1`
   - This script syncs loose `.c` files to BOTH DS local + Workshop cache AND removes stale `.pak` files.
   - **NEVER** delete the Workshop cache directory itself — only remove `.pak` and `.rdb` files from it.

2. **`-mod=` does NOT exist in Arma Reforger** (that is Arma 3/DayZ). The engine ignores it WITHOUT warning.

3. **GUID `58D0FB3206B6F859` = the base game**. Our mod GUID = `7E5A1C9B3D8F2406`. Never swap or reuse them (pre-commit hook guards this).

## Mandatory workflow — DS is the only dev workflow

| Task | Exact action |
|---|---|
| Start bridge | `start_bridge.bat` (port 5001, auto-elevates admin for voice PTT key) |
| Start DS with mod | `taskkill /F /IM ArmaReforgerServer.exe` → `launch_ds.bat` (uses `server.json` + `game.mods[]`, mod from BI Workshop) |
| Connect game client | Launch Reforger normally → Multiplayer → Direct Connect → `127.0.0.1:2001` |
| Verify result | ~55s after DS start: `powershell -NoProfile -File scripts\check_latest_log.ps1` |
| Claiming "done" | ONLY if that script reports `OK` |
| Writing game scripts | FIRST read `@docs/skills/enforce-script.md`; only use patterns from it |
| After editing .c files | Run `powershell -NoProfile -File scripts\sync_mod.ps1` (syncs to DS + Workshop cache, removes .pak) |
| Editing AGENTS.md | run `scripts\sync-agent-docs.bat` before committing |

NEVER: invent your own launch commands · reuse GUIDs · `git add -f` on gitignored files · commit `config.json` · claim "fixed" without log evidence.

## What this project is

LLM-driven squad control for Arma Reforger. An Enforce-script mod in the game talks over HTTP to a local FastAPI bridge, which forwards requests to an LLM (Ollama-compatible proxy on the LAN). The bridge also hosts the voice pipeline (Whisper STT), TTS feedback, and per-soldier memory system.

## Stack
- **Game mod**: Arma Reforger (build 190965), Enforce script (`.c`). Addon = `reforger_mod/addons/ReforgerLLMSquad/` with `addon.gproj`
- **Bridge**: Python 3.11, FastAPI + uvicorn + pydantic + openai client. Entry: `python_bridge/main.py`. Config: `python_bridge/config.json` (GITIGNORED — copy from `config.example.json`)
- **LLM**: Ollama-compatible proxy `http://192.168.1.35:11434/v1`, model `llama3.2-3b`
- **Platform**: Windows-only paths. Game dir: `Q:\SteamLibrary\steamapps\common\Arma Reforger`
- **DS dir**: `Q:\SteamLibrary\steamapps\common\Arma Reforger Server`
- **Logs**: `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<timestamp>\console.log`
- **Launchers**: `start_bridge.bat` (bridge, port 5001), `launch_ds.bat` (dedicated server)

## Does NOT exist in Reforger/Enforce (anti-hallucination list)
Never invent these — every single one has already gone wrong once:
- CLI: `-mod`, `-mod=`, `@modmap`
- Enforce: `modclass`, nested classes (class-in-class), `ref RestContext`, `World.GetGameTime()`, `event` as variable name (reserved keyword)
- REST: `new RestContext()`, `SetURL()`, `SetMethod(RestMethod.*)`, `SetBody()`, `Start()`
  → correct: `GetGame().GetRestApi().GetContext(url)` + `GET(cb, path)` / `POST(cb, path, body)` + `RestCallback` (see `@docs/skills/enforce-script.md` §3)
- Addon metadata: `addon.json`, `gproj.conf` → correct: `addon.gproj`
- Character controllers: `ChimeraCharacterController`, `SCR_CharacterController` — NOT available as script types (engine-internal sealed classes)

## Critical rules (hard-won lessons)

1. **Testing is empirical**: kill → `launch_ds.bat` → ~55s → `check_latest_log.ps1`. Crash signature: log ~1145 bytes. `SCRIPT (E)` in base-game `.c` files AFTER your file = cascade noise; fix YOUR first error first.
2. **Route sync**: endpoints in `LLMBridge.c` must match `main.py`. Game sends via GET `?data=<json>` (POST body doesn't transmit in Enforce). Endpoints: `/health`, `/sitrep`, `/command`, `/status`, `/waypoint`, `/orders`, `/ai_thought`, `/stavka`, `/voice`, `/tts`, `/soldiers`, `/dashboard` (web UI).
3. **Port sync**: bridge runs on **5001** (config.json, bats, LLMBridge default URL).
4. **Never commit secrets.** `config.json` (API key) is gitignored + pre-commit blocked; only commit `config.example.json`.
5. Never change the GUID in `addon.gproj` (pre-commit hook blocks this).
6. **DS mod loading**: `game.mods[]` with `modId = addon GUID` (16-char hex from `addon.gproj`, NOT Steam numeric ID). DS downloads mod from BI Workshop → scripts compile + execute. Mod MUST be published to BI Workshop (even as unlisted).
7. **Workshop cache overrides DS local addons (CRITICAL)**: DS caches mod in `Documents\My Games\ArmaReforger\addons\ReforgerLLMSquadControl_7E5A1C9B3D8F2406\`. This OVERRIDES the DS local addons dir. You MUST sync .c files to BOTH locations via `sync_mod.ps1`. #1 cause of phantom compile errors.
8. **Cached workshop mods**: If the user previously joined a community server, 100+ workshop mods may be cached in `addons\`. These cause `ADDON_LOAD_ERROR`. Fix: move them to `addons_disabled/` subfolder.
9. **`SCR_AIGroup.IsFull()` does NOT exist**. Use `GetPlayerAndAgentCount()` vs `GetMaxMembers()` instead.
10. **REST callback GC**: Inline `new RestCallback(...)` is garbage-collected before the async HTTP response arrives. Fix: store in `ref array<ref MyCallback> m_aActiveCallbacks`.
11. **POST body never transmits**: `RestContext.POST(cb, path, body)` sends the request but body arrives empty (`Content-Length: 0`). Fix: send data via GET query param (`/sitrep?data=<urlencoded_json>`). Enforce has no built-in URL encoder — write your own.
12. **Confirmed soldier prefabs** (from vanilla SDK source, NOT invented):
    - US: `{5B1996C05B1E51A4}Prefabs/Characters/Factions/BLUFOR/US_Army/Character_US_AR.et` (Automatic Rifleman)
    - US unarmed: `{2F912ED6E399FF47}Prefabs/Characters/Factions/BLUFOR/US_Army/Character_US_Unarmed.et`
    - USSR: `{DCB41B3746FDD1BE}Prefabs/Characters/OPFOR/USSR_Army/Character_USSR_Rifleman.et`
13. **SpawnUnits() does NOT spawn AI**: Uses `m_aUnitPrefabSlots` (editor-set array). Dynamic groups have empty slots. Fix: manual spawn via `SpawnEntityPrefabEx()` + `AIControlComponent.GetControlAIAgent()` + `ActivateAI()` + `group.AddAgent()`.
14. **AIFormationComponent required**: Without `SetFormation("Column")`, spawned AI stand still. Set formation after spawning.
15. **DS scenarioId**: `{ECC61978EDCC2B5A}Missions/23_Campaign.conf` (NOT the `.ent` world file).
16. **Live orders system**: Game polls `GET /orders` every 2s. Commands: `spawn`, `hold`, `move`, `status`, `despawn`, `formation`, `follow`, `despawn_opfor`, `medic`.
17. **Master/Slave group architecture (CRITICAL for MP)**: Player-facing master group + AI-facing slave group. Use `AddAgentFromControlledEntity()` (broadcasts via RPL) not `AddAgent()` (no broadcast). Slave group prefab: `{04D3B38E23F51754}Prefabs/AI/Groups/Slave_Group.et`.
18. **SCR_AICombatComponent crash**: If AI is activated before slave group's `SCR_AIGroupUtilityComponent` initializes, `GetGroupUtilityComponent()` returns null → VM Exception. Fix: add AI to group FIRST, then delay `ActivateAI()` by 500ms via `CallLater`.
19. **Auto-follow default**: After spawning AI, create Follow waypoint (`{A0509D3C4DD4475E}Prefabs/AI/Waypoints/AIWaypoint_Follow.et`) at player position.
20. **Uvicorn HTTP Upgrade headers**: Reforger sends `Connection: Upgrade` on normal REST requests. Monkey-patch `H11Protocol._should_upgrade` and `HttpToolsProtocol._should_upgrade` in `main.py` to return `False` for non-WebSocket upgrades.
21. **`ref` arrays with engine classes**: `ref` is only valid for script-defined classes. Engine classes (`SCR_AIGroup`, `IEntity`, `AIAgent`) CANNOT use `ref` as element type. Correct: `ref array<SCR_AIGroup>`. Wrong: `ref array<ref SCR_AIGroup>` or `array<SCR_AIGroup>`.
22. **ChimeraWorld uses CastFrom(), NOT Cast()**: `ChimeraWorld.CastFrom(GetGame().GetWorld())` (static method, not inherited `.Cast()`).
23. **Enforce Script `+=` does not auto-convert int to string**: `str += int;` fails. Fix: `str += "" + int;`. Also `int.ToString()` is NOT valid — use `"" + value`.
24. **RPL authority for entity spawning on DS**: Always check `Replication.IsServer()` before spawning. REST calls and SITREPs work fine without authority.
25. **AutoSquad retry + dynamic group lookup**: On DS, players spawn BEFORE joining a group. AutoSquad retries every 10s for 3min + dynamically looks up group each SITREP.
26. **QueryEntitiesBySphere needs callback function**: Define module-level `bool QueryEntityCallback(IEntity ent)` and call `QueryEntitiesBySphere(pos, 60, QueryEntityCallback)`.
27. **EGetOutType enum not publicly documented**: Use `AskOwnerToGetOutFromVehicle()` instead of `GetOutVehicle()`.
28. **ChimeraCharacterController NOT available as script type**: Cannot use `Cast()` or `FindComponent()` for character controllers. Health state detection WORKS via `SCR_DamageManagerComponent` (extends `DamageManagerComponent`): `IsDestroyed()` → dead, `GetHealthScaled() < 0.15` → downed. NOTE: `ShouldBeUnconscious()` and `IsIndefinitelyUnconscious()` on `SCR_CharacterDamageManagerComponent` are PROTECTED — compile error if called. API source: `Arma Reforger Tools\Workbench\docs\ArmaReforgerScriptAPIPublic.zip` (local!).
29. **Enforce Script `%` modulo operator not supported on floats**: Use fixed constants or integer math instead.
30. **Faction must be set via FactionManager, not group components**: `SCR_AIGroup` does NOT have `FactionAffiliationComponent`. Use `FactionManager.GetPlayerFaction(playerID)` directly and set faction on each soldier via `FactionAffiliationComponent.SetAffiliatedFaction()`.
31. **Dynamic faction**: Squad soldier prefab + OPFOR faction adapt to player faction. US player → US squad + USSR OPFOR. USSR player → USSR squad + US OPFOR.
32. **Stavka disabled**: Stavka OPFOR spawning disabled — vanilla 23_Campaign already has OPFOR/FIA forces. Controller kept alive for future use.
33. **F5: Battle Memory**: Bridge maintains rolling `battle_log` (15 events) in `app_state`. Included in LLM prompt. Events: ORDER, CONTACT, CRITICAL, RECOVERY.
34. **F6: Medic Rescue (IMPLEMENTED)**: `leader_state` (alive/downed/dead) in SITREP JSON + fingerprint. MEDIC action in LLM enum. Detection via `SCR_DamageManagerComponent` (rule 28).
35. **Event-driven thoughts**: Replaced 30s timer with event detection. Thoughts trigger on: contact, clear, order_change, casualty, idle (60s fallback). 15s cooldown.
36. **`generate_ai_thoughts()` LLM call**: The F7 rewrite accidentally deleted the LLM call + return (function always returned `[]`). Restored. ALWAYS verify a function's return path after a refactor that touches it.
37. **Ollama proxy JSON output**: `response_format=json_object` is NOT reliable — proxy may prepend prose or wrap in ```json fences. Always parse LLM JSON via `extract_json_block()` (first `{...}` span, fence stripping), never raw `json.loads()`.
38. **Two bridge processes trap**: `start_bridge.bat` + manual starts can leave TWO bridges running (venv + uv python). Old one holds port 5001; new code never activates. Check `Get-CimInstance Win32_Process` for multiple `main.py` before debugging weird behavior.
39. **Ollama max_tokens truncation**: With `response_format=json_object` the proxy may hit `finish: length` and return TRUNCATED JSON (no closing `}`). `json.loads()` then fails. Raise max_tokens generously (600+) when output contains tool calls, and use `_repair_truncated_json()` to salvage member objects.
40. **LLM output schema drift**: llama3.2-3b does NOT reliably return `{"thoughts": [...]}` — sometimes a bare member object, sometimes prose + fences, sometimes truncated. `extract_json_block()` must handle: prose prefix, ```json fences, wrapper dict, bare objects (collect as thoughts), truncated spans (per-object repair).
41. **Windows console cp1252**: `logging` to console crashes on unicode chars (→, em-dash) in log strings under cp1252. Use ASCII (`->`) in log/result strings that may hit the console.
36. **Eureka Workflow (MANDATORY)**: At every eureka moment: update AGENTS.md → `sync-agent-docs.bat` → commit → `git push origin main`.
37. **AGENTS.md Maintenance**: Keep current. After every feature → update Status & roadmap. After every lesson → add a rule. Remove obsolete info. Push to GitHub.

## Skills (detail docs — read when working in that area)
- Reforger mod structure/loading/GUIDs → `@docs/skills/arma-reforger-modding.md`
- Enforce script language rules + REST API → `@docs/skills/enforce-script.md`
- Debug workflow (console.log, test cycle) → `@docs/skills/reforger-debugging.md`

## Status & roadmap

### Completed
- **F0/F1.1**: Mod loads, scripts compile, game reaches main menu
- **F1.2**: Auto-squad: player spawns → finds group → sets leader → spawns 5 AI soldiers
- **F1.3**: Route sync game↔bridge, REST callback GC fix, POST body fix (GET ?data=)
- **F2.x**: Live orders (spawn/hold/move/despawn/formation/follow), manual AI spawn pattern, AIFormationComponent
- **DS with mod working**: `game.mods[]` + BI Workshop, scripts compile + execute on DS
- **F3.1/F3.2/F3.3**: Stavka OPFOR Strategic AI (now disabled — vanilla has OPFOR)
- **Phase 2**: Voice pipeline (Whisper STT, PTT key, transcription → LLM → orders)
- **F3.5**: Environment scanning (time/day/night, terrain elevation)
- **Phase 3**: TTS squad feedback (edge-tts + pyttsx3 fallback)
- **F4**: Vehicle mount/dismount commands + Stavka offset fix
- **F5**: Battle Memory (rolling battle_log in LLM prompt)
- **F6**: Medic Rescue (leader_state tracking, MEDIC action, downed detection via SCR_DamageManagerComponent)
- **F7**: Individual AI soldier memory (`ai_soldiers/{name}.json` per soldier)
- **Event-driven thoughts** (contact/clear/order_change/casualty/idle, 15s cooldown)
- **F8.1**: Soldier identity + backstory (deterministic, personality-matched) + per-soldier conversation history
- **Dynamic faction** (squad + OPFOR adapt to player faction)
- **Faction fix** (FactionManager.GetPlayerFaction, not group components)
- **Slave group waypoint fix**: ExecuteWaypoint/ClearSquadWaypoints/GetSquadPosition now use FindAIGroup() which targets the SLAVE group (where AI agents live) instead of the MASTER group. SetGroupFormation also fixed to target slave group.
- **Web Dashboard** (`GET /dashboard`): Fixed header/left/right/footer grid layout, dark mode (toggle), mobile responsive. Command buttons: spawn reinforcements, hold, move (E/W/N/S + custom dx/dz), follow, formation, medic, despawn, despawn_opfor. Polls /health (3s), /status (5s), /soldiers (10s). SITREP squad cards, enemy contacts, battle log, AI thoughts, soldier roster panels.

### Development roadmap
- **F7: Individual AI Soldier Memory (IMPLEMENTED)**: Each soldier gets personal JSON memory file (`ai_soldiers/{name}.json`). Tracks: name, personality, birth_date, personal event log (50 max), opinions, mood, relationships, kills, battles survived, status (alive/dead). Death = retain 7 days → archive to `graveyard/`. Thoughts generated from personal history.

- **F8.1: Soldier Identity + Backstory (IMPLEMENTED)**: Deterministic identity per soldier (rank, role, age, origin, deployments, time in theater) + generated backstory matching their personality. Stored in memory file (`identity` + `backstory` fields). Identity + backstory + own thought history are fed into every thought-generation prompt (rank/role-aware voices).
- **F8.2: Per-soldier conversation history (IMPLEMENTED)**: `thought_history` (rolling 10) in each soldier's memory file. Previous own thoughts are included as context in the next generation, so soldiers have continuity instead of amnesia.
- **F8.1 bugfix: thoughts now actually generate**: The F7 rewrite accidentally deleted the LLM call + return in `generate_ai_thoughts()` (always returned `[]`). Restored with robust `extract_json_block()` — the Ollama proxy sometimes prepends prose/wraps JSON in ```json fences, which broke `json.loads()`.
- **F8.3: Soldier Tools — agents trigger game logic (IMPLEMENTED)**: Soldiers may emit an optional `tool` field in their thought JSON. Tools: `report_contact(direction, distance, count)`, `report_clear()`, `request_orders()`, `report_status(health, ammo)`, `call_medic(target)` → queues a MEDIC order, `suggest_tactic(formation, direction)` → queues a FORMATION order. Tool calls become real entries in `pending_orders` (game polls /orders every 2s) or battle_log events — soldiers are agents, not commentators.
- **F8.3b: Tool calls visible in-game (IMPLEMENTED)**: `LLMBridge.c ProcessThoughts()` now parses the optional `tool` field and appends `(tool_name)` to the radio-chat message. Game-side event detection extended with `leader_downed`/`leader_recovered` (via `GetPlayerLifeState()` + `m_sLastLeaderState`) — the bridge already supported those events, the game now triggers them.
- **F8.4: Social dynamics — bonds & opinions (IMPLEMENTED)**: Soldiers now build relationships from shared events. Each event (contact/clear/casualty/leader_downed/...) nudges a sentiment score toward every squadmate, modified by personality friction (VETERAN↔ROOKIE, CAUTIOUS↔AGGRESSIVE/JOKER). Strong scores materialize as stored opinions (brother-in-arms/trusted/reliable/okay/reckless/unpredictable), fed into thought prompts via `get_social_summary()`. The `relationships`/`opinions` fields in memory files are now actually used.
- **F8.5: Kill attribution + enriched roster (IMPLEMENTED)**: When SITREP `enemy_count` drops, the squad gets credited — kills are attributed round-robin to squad members (per-soldier `kills` counter + `kill` event in memory, battle_log entry). `/soldiers` now returns rank/role/relationships/opinions; dashboard roster shows rank, role, personality, mood, relationship badges and latest opinion.
- **F8.6: Anti-parrot + chain of command (IMPLEMENTED)**: Thought prompt now explicitly forbids repeating own earlier thoughts (the model was parroting its own thought_history — "Time to put our money where our mouth is" every round). System prompt also establishes the CO = the player; soldiers address the CO and wait for orders.
- **F8.7: Adjutant sees squad psyche (IMPLEMENTED)**: `get_situation_text()` now includes each soldier's `mood` + `last_thought` — the order-issuing LLM knows how the squad feels (nervous rookie, impatient aggressor), not just positions. Full chain: soldiers think (identity/backstory/relationships) → soldiers act (tools) → adjutant sees moods/thoughts → adjutant orders → game executes.
- **F8: AI Soldiers as Autonomous Agents (VISION)**: Evolution of F7. Each AI soldier is an autonomous LLM agent with:
  - **Identity System Prompt**: Name, faction, rank, role, chain of command (CO = player), squadmates, expectations
  - **Backstory**: Personal history (age, origin, time in theater, prior deployments, personality traits). From game data or generated at spawn. A rookie sounds different from a veteran.
  - **Available Tools**: The soldier LLM can call tools to interact with the game world:
    - `report_contact(direction, distance, count)` — report enemy sighting to squad
    - `report_clear()` — report area is clear
    - `request_orders()` — ask CO for new orders
    - `report_status(health, ammo)` — report own condition
    - `call_medic(target)` — request medical help for a squadmate
    - `suggest_tactic(formation, direction)` — suggest a tactical change
  - **Agent, not commentator**: Observe → decide → act. Thoughts are one output; tool calls trigger game logic.
  - **Per-soldier conversation history**: Each soldier maintains their own LLM messages array (not just flat event log).
  - **Game backstory integration**: Use Reforger's character entity backstory/lore in system prompt if available.

## References
- `MOD_SETUP.md` — launch error diagnosis
- BI wiki: `Arma_Reforger:Startup_Parameters`, `:Mod_Project_Setup`, `:REST_API_Usage` (community.bistudio.com)

## Maintenance
- This file = source of truth. `CLAUDE.md` and `.goosehints` are sync copies (Windows: no symlinks).
- After editing: run `scripts\sync-agent-docs.bat`. Pre-commit hook (`core.hooksPath=.githooks`) blocks drift, secrets and GUID changes.
- Language: **English everywhere** — code, comments, docs, commit messages. Commits: short, feature-scoped.
