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
42. **Voice pipeline never started (FIXED)**: `voice_handler.start()` was NEVER called and `on_transcription` stayed `None` — the config said enabled:true but nothing ran (`running:false` in /voice). Fixed in `startup_event()`: wire the transcription callback (text → `call_llm` → `pending_orders` + TTS reply) and call `start()`. ALSO: `keyboard`, `faster-whisper`, `pyttsx3`, `edge-tts` were missing from the venv — `pip install` them. STT verified end-to-end: pyttsx3-generated WAV → Whisper tiny → exact transcription.
43. **STT is NOT in-game radio**: The voice pipeline listens on a GLOBAL PTT key (F24 default) capturing the microphone via `sounddevice` — it does NOT hook into Reforger's in-game radio/VOIP. It works while the game is running, but it's a separate button. In-game radio integration would need mod-side changes (game streams radio audio to the bridge).
44. **TTS never started (FIXED)**: `tts_handler.start()` was never called — `_running` stayed False so `speak()` short-circuited and ALL squad audio was silent. Same class of bug as voice_handler (rule 42). Check `/tts` shows `running:true` after startup.
45. **Event detection shift bug (FIXED)**: LLMBridge.c shifted `m_iLastEnemyCount/m_sLastLLMAction/m_iLastSquadCount` EVERY FRAME, but the async REST callback updates the "current" values frames later — so contact/clear/casualty/order_change events could never fire. Shift must happen ONLY when a new SITREP is sent.
46. **IndexOfFrom(-1) crash risk (FIXED)**: Enforce `IndexOfFrom(negativeIndex, ...)` searches from a bogus position. Guard with `if (idx >= 0)` BEFORE using the result as a search origin — found in move-offset and formation parsers.
47. **Tool JSON misattribution (FIXED)**: `ExtractThoughtTool` searched for `"tool"` past the current object's `}` — a later soldier's tool could be attached to the current thought. Bound the search to the current object span.
48. **LLM prepends rank to names (FIXED)**: llama3.2-3b sometimes returns `"name": "CPL Alpha_1"`. `sanitize_soldier_name()` strips rank tokens so memory files stay canonical (`Alpha_1.json`).
49. **call_medic tool order ignored by game (FIXED)**: Soldier tool `call_medic` queued `{"cmd":"medic"}` but the game order parser had no `medic` case ("Unknown order: medic"). Added — same rescue logic as the SITREP MEDIC action. Also: voice pipeline sends `action.lower()` (engage/suppress/flank/retreat) which the order parser didn't know — added as move/attack aliases.
50. **Unparseable LLM output in call_llm/stavka (FIXED)**: `call_llm` and `generate_stavka_orders` used raw `json.loads()` on proxy output — same prose/fence failure as thoughts (rule 40). Now use `extract_json_block()` with a HOLD fallback.
51. **LiveDespawnSquad despawnt uit master i.p.v. slave group (FIXED)**: AI lives in the SLAVE group (after MoveAgentsToSlaveGroup); despawning from master found 0 agents. Now targets the slave group with master fallback. Also: **Enforce has NO ternary `? :` operator** — compile error, use if/else.
52. **Respawn never re-linked (FIXED)**: `OnControlledEntityChanged` guard `if (m_bAutoSquadDone && from) return;` blocked ALL re-triggers after first spawn — the RESPAWN branch in DeferredAutoSquad was dead code. Now: skip only if the old entity is still alive (`SCR_DamageManagerComponent.IsDestroyed()` check); destroyed entity = death/respawn → re-run squad flow.
53. **Hardcoded LiveSpawnSquad(1) (FIXED)**: `spawn` order used playerID 1; after reconnect the player may have another ID. Added `GetFirstPlayerID()` dynamic lookup.
54. **Voice PTT races (FIXED)**: (a) `_on_ptt_release` concatenated `self._audio_chunks` outside try — a fast re-press resets the list mid-concat → ValueError → keyboard hook thread dies. Now copies chunks first, try/except. (b) `_on_transcription` (blocking LLM call, 2-5s) ran in the hook thread → PTT presses during transcription were lost. Now runs in a daemon thread.
55. **TTS edge-tts loop race (FIXED)**: every `speak()` spawns a thread; two overlapping calls hit `run_until_complete` on a running loop → "event loop already running" → silent fallback to pyttsx3. Guarded the shared loop with `self._lock`.
56. **check_latest_log.ps1 missed non-LLMBridge errors (FIXED)**: the `$ours` filter matched only `LLMBridge|ReforgerLLMSquad`, but error lines carry the file name (`@"scripts/Game/AutoSquadManager.c,772"`) — errors in AutoSquadManager/Stavka/AutoConnect were invisible unless "Can't compile" appeared. Now matches all our script files.
57. **Stavka parser has the same IndexOfFrom(-1) pattern** (rules 46) in offset parsing — but it's DISABLED code (`PollStavka` early-returns). Re-enable with care: fix those guards first.
58. **DS loads mod from LOCAL addons dir, not Workshop**: `server.json` has `"mods": []` but the mod works — the DS picks up `./addons/ReforgerLLMSquad/` (gproj GUID 7E5A1C9B3D8F2406 in log). `game.mods[]` is NOT required on this setup. The Workshop cache path matters for CLIENTS (and as the override source per rule 7).
59. **extract_json_block dict-or-None contract (FIXED)**: llama3.2-3b sometimes returns a bare JSON string literal (`"Alpha_1: thought"`) or array — `json.loads` succeeds and returns a non-dict, and any caller doing `data.get(...)` crashes with `'str' object has no attribute 'get'` (this was killing 2-3 of 4 per-soldier calls per cycle). `extract_json_block` now returns `None` for non-dict results, and the per-soldier parser salvages `{"thoughts": [<string>]}` wrappers. Rule 40 family — ALWAYS enforce dict-or-None at the parser, never trust the caller to guard.
60. **uv venv shim = two python.exe, ONE bridge**: `venv\Scripts\python.exe` created by `uv venv` is a launcher that spawns the real uv-managed python — `Get-CimInstance Win32_Process` shows TWO `python.exe main.py` entries (parent/child, same CreationDate). This is NOT the rule-38 two-bridge trap. Check `ParentProcessId` before assuming a duplicate.
61. **A.2 chatter uses previous-cycle semantics**: squadmate chatter is read from memory FILES (last assistant message in each squadmate's `conversation`), so soldiers react to what squadmates said in the PREVIOUS generation cycle — generation stays parallel (no sequential coupling). First cycle = empty chatter, graceful. Chatter is persisted in the conversation brief (`| heard: ...`) so reactions stay in context.
62. **Variable clobbering in generate_ai_thoughts (FIXED)**: the function built `result = {"thoughts": [...]}`, then the tool loop did `result = handle_soldier_tool(...)` — reassigning the return value to the tool string. Whenever a soldier called a tool, `/ai_thought` returned a bare string instead of the dict ("string indices must be integers" for the game). Caught by an A.3 unit test. Rule 36 family: after ANY refactor, verify every return path — and don't reuse a return-value variable for intermediate results.
63. **B.1 death detection is dormant without game-side `alive` reporting**: `LLMBridge.c`'s `m_aSquadMembers` is a FIXED 5-member array, never filtered — SITREPs always list all 5 names, so bridge-side missing-name detection can never fire. `SendSITREP()` must report per-member `"alive": false` (check `SCR_DamageManagerComponent.IsDestroyed()` per agent) — game-side follow-up for V.1.
64. **Death grace period (B.1)**: a member absent for ONE thought cycle is NOT dead — transient gaps happen (respawn re-link per rule 52, despawn → re-spawn rebuilds). Bridge marks dead only when: (a) CONFIRMED via `alive:false` in the SITREP, or (b) missing for `game.death_grace_cycles` (default 2) consecutive thought cycles. The absence counter accumulates over "known" members (previous squad ∪ already-missing), NOT just last cycle's squad — otherwise a member who drops out of `last_squad_names` stops accumulating.
65. **Replacement resurrection must check `alive` (B.1)**: a dead member still reported `alive:false` is NOT a replacement — without the guard, every thought cycle resurrects → re-kills → re-grieves them (duplicate grief opinions/events). Resurrect only when the game reports the member alive.
66. **Dead members don't speak (B.1)**: skip `alive:false` members in per-soldier AND batched thought generation; the adjutant situation text marks them `[KIA - confirmed dead]` so the LLM knows the squad is down a soldier.
67. **update_social_bonds clobbers "mourned" (B.1)**: it recomputes relationship labels for every squad member — if dead members are included, the "casualty" event (+2 respect) overwrites the "mourned" relationship set during grief. Pass only ALIVE members.
68. **Session boundary reset (B.1)**: a SITREP gap > 90s = player disconnected / new session. `_check_session_boundary()` (called in `receive_sitrep`) clears `last_squad_names` + `missing_soldiers` so a reconnect with a different squad composition does NOT false-KIA the previous session's absentees.
69. **Eureka Workflow (MANDATORY)**: At every eureka moment: update AGENTS.md → `sync-agent-docs.bat` → commit → `git push origin main`.
70. **AGENTS.md Maintenance**: Keep current. After every feature → update Status & roadmap. After every lesson → add a rule. Remove obsolete info. Push to GitHub.
71. **B.2 rank promotion is cumulative (FIXED)**: `check_rank_progression()` originally promoted ONE rank per call — a soldier with score 18 (enough for SGT) climbed PVT→PFC only. Deeds accumulate, so a single check must promote as far as the score allows (`while` loop to SGT). Unit test `test_multi_rank_promotion` guards this.
72. **B.5 was implemented but AGENTS.md lagged**: `_write_after_action_report()` + session-boundary wiring + prompt injection existed in code (auto-committed leftover changes) while the roadmap still listed B.5 as pending. Lesson: when taking over a repo, VERIFY code state against AGENTS.md instead of trusting the roadmap text — the code is the source of truth.
73. **B.4 cross-restart state must live in files, not app_state**: B.5's `last_report_summary` was app_state-only — lost on bridge restart, so the squad "forgot" previous deployments. Fix: `_write_after_action_report()` also writes `reports/last_summary.json` + per-soldier `previous_deployments` (last 3, deduped by summary equality), restored in `startup_event()` via `_load_last_report_summary()`.
74. **B.4 fatigue writes only on LEVEL change**: `update_soldier_fatigue()` compares `mem["fatigue"]["level"]` and skips `save_soldier_memory()` when unchanged — SITREPs arrive every 2-10s and writing JSON per SITREP would churn the disk + log. Coarse state (0-3) makes this cheap.
75. **B.4 event moods beat fatigue drift**: exhaustion drifts rested moods (calm/steady/confident/neutral) toward tired/worn, but a nervous/alert soldier stays nervous — fear wins over exhaustion. Drift only when `fatigue.level >= 2` and mood ∈ drift set; otherwise you'd erase event-driven psychology (F8.4).
76. **E.3 bare error counters are useless for diagnosis**: `app_state["errors"] += 1` told you SOMETHING failed but never what/where — during V.1 live testing that means digging through bridge.log. Every error site now goes through `_record_error(source, exc)` which keeps a rolling 10-entry window (time, source, message, 3-frame traceback) exposed in `/health.recent_errors`. Lesson: count AND surface; a counter without context is a TODO comment.
77. **C.5 soldiers propose, the CO disposes**: `suggest_tactic` no longer auto-executes — it lands in `pending_suggestions` (dashboard "CO Suggestions" panel) and only queues the formation order after the player accepts (`_approve_suggestion` → `pending_orders`). Design principle: tools that change game state need a human approval gate; tools that only report (report_contact etc.) stay instant. Note: `handle_soldier_tool` already ignores unknown tool names gracefully ("push forward" etc. — schema drift, rule 40 family).

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
- **Phase 2**: Voice pipeline (Whisper STT, PTT key, transcription → LLM → orders) — REPAIRED: was never started (start() never called, callback None); now wired in startup_event, dependencies installed, STT verified end-to-end
- **F3.5**: Environment scanning (time/day/night, terrain elevation)
- **Phase 3**: TTS squad feedback (edge-tts + pyttsx3 fallback)
- **F4**: Vehicle mount/dismount commands + Stavka offset fix
- **F5**: Battle Memory (rolling battle_log in LLM prompt)
- **F6**: Medic Rescue (leader_state tracking, MEDIC action, downed detection via SCR_DamageManagerComponent)
- **F7**: Individual AI soldier memory (`ai_soldiers/{name}.json` per soldier)
- **Event-driven thoughts** (contact/clear/order_change/casualty/idle, 15s cooldown)
- **F8.1**: Soldier identity + backstory (deterministic, personality-matched) + per-soldier conversation history
- **F8.2**: Per-soldier conversation history — `thought_history` (rolling 10) per soldier, own thoughts as context (continuity, no amnesia)
- **F8.3**: Soldier tools — report_contact/report_clear/request_orders/report_status/call_medic/suggest_tactic → real orders (medic/formation) + battle_log events; agents, not commentators
- **F8.3b**: Tool calls visible in-game (radio chat) + leader_downed/leader_recovered thought events from game side
- **F8.4**: Social dynamics — bonds & opinions from shared events, personality friction (VETERAN↔ROOKIE etc.)
- **F8.5**: Kill attribution from enemy_count drops + enriched roster (rank/role/relationships/opinions)
- **F8.6**: Anti-parrot prompt + chain of command (CO = player)
- **F8.7**: Adjutant sees squad psyche (mood + last_thought in situation text) — full layered chain
- **F8.8**: Opinion refresh on score change + graveyard section in dashboard
- **F8.9**: Audible soldier tool calls via TTS with per-soldier voices
- **F8.10**: Soldier detail panel in dashboard (backstory, event log, thought history)
- **F8.11**: Voice/STT status panel in dashboard (PTT key, model state, last transcription)
- **A.1 Per-soldier LLM conversations** (committed 560ba126): ONE private conversation per soldier — system prompt with own identity+backstory+personality+CoC+tools, own `conversation` log as real chat turns (last 6 exchanges), current situation as latest turn. One LLM call per soldier + batched fallback. Unit tests: `python_bridge/test_soldier_thoughts.py`.
- **A.2 Soldier-to-soldier chatter** (committed a0ddc34): each soldier's prompt includes "Squadmate chatter" — the most recent transmission of each squadmate (read from their memory file, previous-cycle semantics, self excluded). System prompt tells soldiers to react/acknowledge/push back. Chatter also persisted in the conversation brief ("| heard: ...") so reactions stay in context. Batched fallback gets "Squadmate chatter heard" per member. Verified live: Alpha_1 reacting to Alpha_3's words across cycles, 0 errors.
- **A.3 Tool consequence awareness** (committed 798f4e6): `handle_soldier_tool()` result ("order queued / event logged") is stored as `last_tool_result` in the soldier's memory and fed into their NEXT prompt as "Your last action's result: ..." — soldiers learn their actions have effects. Same for batched member lines. Also FIXED a pre-existing bug this exposed: `generate_ai_thoughts` reused the variable `result` for the tool string, clobbering the `{"thoughts": ...}` return dict whenever a tool fired (rule 62).
- **A.4 Game backstory integration (research + bridge plumbing)**: RESULT — in-game identity IS readable from script: `SCR_CharacterIdentityComponent.GetFormattedFullName(out format, out name, out alias, out surname)` + `Identity.GetName()/GetAlias()/GetSurname()` (confirmed in local `ArmaReforgerScriptAPIPublic.zip`). Backstory/lore fields do NOT exist (`Identity` config = name/alias/surname/sound/visual only) — bridge-generated backstories remain the lore source. Bridge now accepts optional `identity` per SITREP squad member and feeds it into the per-soldier system prompt ("In-game identity (military records)"). REMAINING (needs live session): game-side LLMBridge.c SITREP should include `identity` via `SCR_CharacterIdentityComponent.GetFormattedFullName()` on each squad member.
- **Bugfix rounds 1-3**: 20+ fixes — TTS/voice never started, event-shift bug, despawn/respawn/playerID, IndexOfFrom(-1) guards, JSON parse hardening, name sanitizer, PTT races, TTS loop race, check_latest_log.ps1 filter (see rules 42-58)
- **Dynamic faction** (squad + OPFOR adapt to player faction)
- **Faction fix** (FactionManager.GetPlayerFaction, not group components)
- **Slave group waypoint fix**: ExecuteWaypoint/ClearSquadWaypoints/GetSquadPosition now use FindAIGroup() which targets the SLAVE group (where AI agents live) instead of the MASTER group. SetGroupFormation also fixed to target slave group.
- **Web Dashboard** (`GET /dashboard`): Fixed header/left/right/footer grid layout, dark mode (toggle), mobile responsive. Command buttons: spawn reinforcements, hold, move (E/W/N/S + custom dx/dz), follow, formation, medic, despawn, despawn_opfor. Polls /health (3s), /status (5s), /soldiers (10s). SITREP squad cards, enemy contacts, battle log, AI thoughts, soldier roster panels.
- **B.1 Legacy & mourning (bridge side)**: death detection with two evidence signals — CONFIRMED (`alive:false` per SITREP member, new field, default True) marks dead immediately; MISSING for `game.death_grace_cycles` (2, config) consecutive thought cycles marks dead after a grace period (protects against transient gaps from respawn re-link/despawn). On death: soldier archived to graveyard with final stats, squadmates get `teammate_kia` grief event + "mourned" relationship + grief opinion (deduped — no re-archive/re-grief churn), dead members stop generating thoughts, adjutant situation text shows `[KIA]`. Replacement with the same callsign resurrects with predecessor legacy ("filling their boots", fed into system prompts). Session-boundary reset (SITREP gap > 90s) prevents false KIA across reconnect. Unit tests: confirmed death, grace period, reappearance, dedup, session boundary, dead-don't-speak. REMAINING (game-side, V.1): `SendSITREP()` must send per-member `alive` (rule 63) — today the fixed 5-member array keeps the missing-name path dormant.
- **B.2 Rank progression**: deeds = `kills*2 + battles_survived*3`; thresholds PFC=4/SPC=8/CPL=12/SGT=16 (config in `RANK_SCORE_THRESHOLDS`). `check_rank_progression()` runs every thought cycle for alive members and promotes as far as the score allows (multi-rank jumps OK). Rank lives in `identity.rank` → automatically changes prompt voice (`get_soldier_identity_summary`) + dashboard. Promotion logs a soldier event + battle-log ORDER event and nudges squadmate relationships (+2 respect via new `promotion` social event). Death resets: a replacement resurrects at their hash-derived base rank with kills/battles zeroed (predecessor stats stay in the legacy string). Unit tests: exact-threshold promotion, multi-rank jump to SGT, no promotion below threshold, replacement reset.
- **B.4 Fatigue & session memory**: fatigue level 0-3 (fresh/tired/exhausted/combat-worn) rises with session time (thresholds in config `fatigue` block: 20/45/75 min) and accelerates with combat intensity (3 CRITICAL or 5 CONTACT events in battle_log). `update_soldier_fatigue()` persists it per soldier (writes ONLY on level change) and drifts rested moods (calm/steady/confident/neutral) toward tired/worn at level 2+ — event moods (nervous/alert) win over fatigue. Fed into prompts: adjutant situation text ("Squad fatigue: …"), per-soldier system prompt ("Your physical state: … let the strain show"), batched member lines. Session memory: `_write_after_action_report()` persists the recap to `reports/last_summary.json` (survives bridge restarts — restored in `startup_event`) AND appends per-soldier `previous_deployments` (last 3, deduped) to each alive member's memory file; per-soldier prompts use the soldier's OWN deployment history first, shared recap as fallback. Fatigue resets to fresh at session end. Exposed in `/health` (session_minutes, fatigue) + `/soldiers` + dashboard (header fatigue pill + roster 🥱 tag). Unit tests: `test_fatigue.py` (20 tests) — level transitions, combat acceleration, mood drift vs event moods, no-write-on-unchanged, persistence, dedup, restart restore, situation text.
- **B.5 After-action report**: on session end (SITREP gap > 90s), bridge writes a battle report (kills, casualties, battle log) to `reports/report_<ts>.json` and feeds a one-line summary into the next session's prompts (per-soldier prompts: "Previous deployment (what the squad remembers)"). Wired via `_check_session_boundary()` before squad-state reset. Summary persisted + per-soldier copies by B.4 (rule 73).
- **E.3 Error surfacing in /health**: all 6 error sites (`call_llm`, `thoughts_batched`, `thought_<name>`, `stavka`, `stavka_unparseable`, `voice_order`) now route through `_record_error(source, exc)` — rolling 10-entry window in `app_state["recent_errors"]` (time, source, error message, 3-frame traceback), exposed as `/health.recent_errors` (last 5). Unit test: counter increment, traceback capture, rolling-window cap. The old bare `errors` counter remains as the aggregate.
- **C.5 Suggestion approval flow**: `suggest_tactic` soldier tool no longer auto-executes — it submits to `app_state["pending_suggestions"]` (id, time, soldier, formation, direction, status). New endpoints: `GET /suggestions` (all, pending + last 5 decided via `_trim_suggestions`), `POST /suggestions` `{id, action: accept|reject}` (accept → `_approve_suggestion` queues the real `formation` order + battle event; reject → battle event) and `{action: accept_all}`. Dashboard: "CO Suggestions" panel in the right sidebar (poll 5s) with ✓/✗ per suggestion + Accept All. Unit tests: no auto-execute, submit pending, approve queues order, undecided stays pending, trim. Live: endpoints verified (empty, accept_all=0, unknown id error); `report_contact` tool verified live through the same dispatch path.

### Development roadmap

North star: **F8 — AI soldiers as autonomous agents** (observe → decide → act).
F8.1–F8.11 are done (see Completed). The list below is the forward path, ordered by priority.

---

#### Phase V — VALIDATE (do this FIRST; everything since F6 is untested live)
- **V.1 LIVE TEST SESSION**: Connect client to `127.0.0.1:2001`, play 15+ min. Verify: auto-squad spawns 5 AI, SITREPs flow (bridge /health players_active=true), thoughts appear in radio chat, tool calls fire, medic/formation orders execute, respawn re-links squad (rule 52 fix), despawn actually removes AI (rule 51 fix). GAME-SIDE TODO (B.1): extend `SendSITREP()` to send per-member `"alive": false` for destroyed agents (rule 63) so bridge death detection + grief actually fire in live play. Fix whatever breaks — this is the current #1 risk.
- **V.2 Voice test with real mic**: Caps Lock PTT → Whisper → order → TTS reply. Verify the race fixes (rules 54-55) hold under real usage.
- **V.3 Battlefield sanity**: enemy contact → thought event "contact" fires within 15s (rule 45 fix), leader downed → leader_downed event + MEDIC order (rule 49 fix).

#### Phase A — AGENT CORE (the real F8: per-soldier LLM agents)
*Phase A is COMPLETE (A.1–A.4 done). Forward path continues at Phase B.*

#### Phase B — DEPTH (memory & consequences)
*B.1–B.5 done (bridge side, see Completed). Forward path:*
- **B.3 Mood affects gameplay**: Nervous/panicked soldiers get reduced accuracy or movement delay (game-side modifier based on memory mood) — mood becomes mechanical, not cosmetic.

#### Phase C — IMMERSION (radio, audio, UI)
*C.5 is done (see Completed). Forward path:*
- **C.1 In-game radio → STT**: Route Reforger's actual radio/VOIP audio to the bridge for transcription (mod-side audio capture). Big effort; only if V.2 shows PTT is unsatisfying.
- **C.2 Radio chatter layer**: Random short squad radio chatter ("Alpha 2, moving up", "clear left") voiced via TTS during quiet periods — the squad sounds alive, not just when events fire.
- **C.3 Per-soldier voice selection in dashboard**: Choose/override each soldier's edge-tts voice (currently fixed by index).
- **C.4 Commander map view**: Dashboard mini-map (squad + enemy positions from SITREP offsets) instead of text-only.

#### Phase D — STRATEGY & MODEL
- **D.1 Stavka re-enable (optional)**: Turn OPFOR strategic AI back on IF the vanilla 23_Campaign OPFOR proves too passive. Must fix the IndexOfFrom(-1) guards (rule 57) first.
- **D.2 Better LLM model**: llama3.2-3b limits thought quality (schema drift, rule 40). Evaluate a 7-14B model on the LAN proxy (faster_whisper stays tiny). Measure: valid-JSON rate, tool-call rate, parrot rate.
- **D.3 Bridge resilience**: auto-restart bridge if health check fails (currently manual); backlog pending_orders across restarts.

#### Phase E — HYGIENE
- **E.1 requirements.txt clean install test**: fresh venv + `pip install -r requirements.txt` must produce a working bridge (deps were missing once — rule 42).
- **E.2 Config-driven tuning**: move magic numbers (thought cooldowns, health thresholds, kill thresholds) to config.json.

*E.3 is done (see Completed).*

---

**Priority order**: V → A → B → C (pick per interest) → D → E. V.1 is non-negotiable before claiming any new feature works.

## References
- `MOD_SETUP.md` — launch error diagnosis
- BI wiki: `Arma_Reforger:Startup_Parameters`, `:Mod_Project_Setup`, `:REST_API_Usage` (community.bistudio.com)

## Maintenance
- This file = source of truth. `CLAUDE.md` and `.goosehints` are sync copies (Windows: no symlinks).
- After editing: run `scripts\sync-agent-docs.bat`. Pre-commit hook (`core.hooksPath=.githooks`) blocks drift, secrets and GUID changes.
- Language: **English everywhere** — code, comments, docs, commit messages. Commits: short, feature-scoped.
