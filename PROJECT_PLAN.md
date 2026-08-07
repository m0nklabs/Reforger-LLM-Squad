# PROJECT PLAN: Reforger LLM Squad Control

> ⚠️ **2026-08-07 — CORRECTED & translated to English.** This plan predates the launch fix and
> contained wrong `-mod` instructions and a wrong bridge port. Those are fixed below, but if
> anything contradicts **AGENTS.md** or **MOD_SETUP.md**, those two win.
> Short version: `-mod` does NOT exist in Reforger → use `launch_reforger.bat`
> (`-addonsDir` + `-addons <GUID>`, working dir = game dir). Bridge port = **5001**.

## Document Status
- **Created**: 2026-08-06
- **Author**: Goose AI Agent
- **Status**: DRAFT — Pending operator approval

---

## 1. PROJECT OVERVIEW

### 1.1 Goal
Build an LLM-powered squad control system for Arma Reforger that lets the operator direct an
AI squad using natural language (text in phase 1, voice in phase 2), with squad members
autonomously reporting observations and status updates.

### 1.2 Architecture
```text
OPERATOR:  launch_reforger.bat                 start_bridge.bat
                |                                   |
                v                                   v
+---------------------+   HTTP    +---------------------+   HTTP    +----------------------+
| Arma Reforger       | --------> | Python Bridge       | --------> | LLM Proxy            |
| LLMBridge.c         | <-------- | FastAPI :5001       | <-------- | 192.168.1.35:11434   |
| (Enforce script)    |   JSON    | /health /sitrep     |  OpenAI   | /v1 (OpenAI-compat)  |
+---------------------+           | /command /status    |   SDK     +----------+-----------+
                                  +---------------------+                      |
                                                                      llama-server
                                                                      (local inference)
```

### 1.3 Data Flow
1. **Game → Python**: Enforce Script collects squad telemetry (positions, health, ammo, enemies) and sends it as JSON via HTTP POST to `localhost:5001/sitrep`
2. **Python → LLM**: Python sends the situation + operator command to the proxy via OpenAI function calling
3. **LLM → Python**: LLM returns structured JSON (`{squad, action, grid, voice_reply}`)
4. **Python → Game**: Python returns the JSON as HTTP response; Enforce Script executes it (waypoints, suppression, etc.)
5. **Game → Operator**: Squad members report via in-game sideChat/radio (phase 1: text, phase 2: TTS audio)

---

## 2. ENVIRONMENT INVENTORY

### 2.1 Game Installation
| Property | Value |
|---|---|
| Game directory | `Q:\SteamLibrary\steamapps\common\Arma Reforger` |
| Executable | `ArmaReforgerSteam.exe` |
| Addons | `addons/core/`, `addons/data/` |
| Main gproj | `addons/data/ArmaReforger.gproj` (GUID `58D0FB3206B6F859`) |
| Workbench (Tools) | Installed (ArmaReforgerWorkbenchSteam.exe seen running) |
| Workshop | Not used — mods are loaded locally via `-addonsDir`/`-addons` |

### 2.2 LLM Proxy
| Property | Value |
|---|---|
| URL | `http://192.168.1.35:11434/v1` |
| API Key | stored in `python_bridge/config.json` (GITIGNORED — never in docs/git) |
| Protocol | OpenAI-compatible (`/v1/chat/completions`) |
| JSON mode | ✅ Tested — `response_format: {type: "json_object"}` works |
| Function calling | ✅ Tested — `tools` + `tool_choice` works |
| Fast model | `llama3` (3B) — 335ms latency, function calling confirmed |
| Smart model | `qwen3.6-35b-fast` (35B MoE A3B) — ~2000ms, thinking model, needs 800+ tokens |
| Cloud fallbacks | GPT-5 series, Claude 3.5, Gemini, etc. via proxy |

### 2.3 Python
| Property | Value |
|---|---|
| Version | Python 3.12.10 (system); project venv reports 3.11 (`main.cpython-311.pyc`) |
| Path | `C:\Users\onyou\AppData\Local\Programs\Python\Python312\` |
| venv | `python_bridge/venv/` (gitignored) |
| Whisper | **Not installed** — phase 2 via `faster-whisper` |

### 2.4 Project Directory
| Path | Content |
|---|---|
| `Q:\GAMES\Reforger-LLM-Squad\` | Project root |
| `...\docs\` | Bohemia SampleMods reference (gitignored) + `docs/skills/` (tracked, lessons-learned) |
| `...\reforger_mod\` | Mod source: `addons/ReforgerLLMSquad/` (addon.gproj + Scripts/Game/LLMBridge.c) |
| `...\python_bridge\` | Python backend (main.py, config.json gitignored, test_client.py) |

### 2.5 Network Reference
| Property | Value |
|---|---|
| Game machine | Windows (localhost) |
| LLM proxy machine | `192.168.1.35` (LAN, same network) |
| Python bridge | localhost (`127.0.0.1:5001`) |
| Game → Python | HTTP POST via `GetGame().GetRestApi().GetContext()` (Enfusion native) |
| Python → Proxy | HTTP via `openai` Python SDK |

---

## 3. CONSTRAINTS & ASSUMPTIONS

### 3.1 Hard Constraints
1. **No Workbench required**: Enforce Script `.c` files are written as plain text. The game compiles scripts at runtime.
2. **No Steam Workshop**: mods are loaded locally via `-addonsDir <path>` + `-addons <GUID>` (corrected 2026-08-07: `-mod` does NOT exist — see AGENTS.md).
3. **No BattlEye server**: single-player or locally hosted. Anti-cheat is not active in single-player.
4. **Enforce Script is not C#**: it looks like it, but has limitations. Classes live in specific folders, `modded class` syntax for overrides. See `docs/skills/enforce-script.md`.

### 3.2 Assumptions
1. The operator can start the game via `launch_reforger.bat` (correct `-addonsDir`/`-addons` + working directory).
2. The game compiles unpacked `.c` files at startup (verified 2026-08-07).
3. The proxy stays available for the full session.
4. Single-player scenarios work without server infrastructure.

---

## 4. PHASED DELIVERY PLAN

### PHASE 1: REST Bridge + AI Squad Control (No Voice)
**Goal**: a working HTTP bridge between Reforger and the LLM proxy, where the game sends
squad telemetry and receives structured commands.

#### F1.1 — Python Bridge (`python_bridge/main.py`) — ✅ DONE
- [x] FastAPI server on `127.0.0.1:5001`
- [x] `/health` endpoint (GET) — pinged by Reforger at mod startup
- [x] `/sitrep` endpoint (POST) — receives squad telemetry JSON from Reforger
- [x] `/command` endpoint (POST) — receives operator text command, forwards to LLM, returns JSON
- [x] OpenAI SDK connection to proxy (`192.168.1.35:11434/v1`)
- [x] Function calling schema: `issue_order(squad, action, grid, voice_reply)`
- [x] JSON validation on all in/outgoing payloads
- [x] Timeout handling with fallback command (HOLD)
- [x] Structured logging to `python_bridge/bridge.log`
- [x] Config file (`python_bridge/config.json`) for all settings

#### F1.2 — Enforce Script (`reforger_mod/addons/ReforgerLLMSquad/Scripts/Game/LLMBridge.c`)
- [x] `LLMBridge` class written and COMPILING (2026-08-07)
- [x] `RestContext` via `GetGame().GetRestApi().GetContext()` (real Enfusion API)
- [x] `RestCallback` subclass for response handling
- [x] `SendSITREP()`, `SendCommand()`, health check, passive mode, timers
- [ ] **Component wiring** (open): `modded class SCR_BaseGameMode` that instantiates
      `LLMBridge` at OnGameStart, calls `Activate()`, and drives `Update()` via
      `GetGame().GetCallqueue().CallLater()` — only then does anything happen in-game
- [ ] `sideChat` radio callbacks for squad status reports

#### F1.3 — Mod Configuration & Route Sync
- [x] `addon.gproj` with own GUID `7E5A1C9B3D8F2406` (replaces the invented `gproj.conf`)
- [x] Mod directory structure under `reforger_mod/addons/ReforgerLLMSquad/`
- [x] Launch parameter documentation: `-addonsDir` + `-addons` — DONE 2026-08-07, see MOD_SETUP.md
- [ ] Route sync: `/waypoint` missing in main.py; `/status` is GET in main.py but POST in LLMBridge

#### F1.4 — Standalone Test Mode
- [x] `python_bridge/test_client.py` — simulates Reforger game state JSON
- [ ] Test without game running: send fake SITREP → receive LLM command
- [ ] Validate that function calling returns correct JSON
- [ ] Latency measurement (input → LLM → command)

#### F1.5 — Phase 1 Validation
- [ ] Python server starts without errors
- [ ] `/health` returns 200 OK
- [ ] Simulated SITREP → LLM → correct JSON command
- [ ] JSON schema validation works (bad input → graceful fallback)
- [ ] Timeout fallback works (LLM > 3s → HOLD command)

---

### PHASE 2: Voice Pipeline (Speech → Squad)
**Goal**: operator speaks into microphone, Whisper converts to text, LLM translates to command.

#### F2.1 — Whisper STT Integration
- [ ] Install `faster-whisper` in the Python venv
- [ ] Microphone capture via `sounddevice`
- [ ] Push-to-Talk key listener (configurable key, default `F24`)
- [ ] Audio → text conversion with latency logging
- [ ] `/voice` endpoint in FastAPI

#### F2.2 — Voice → LLM → Game Pipeline
- [ ] Audio capture → Whisper transcription
- [ ] Transcription → `/command` endpoint (reuse phase 1 logic)
- [ ] LLM → JSON command → Reforger
- [ ] End-to-end latency measurement and logging

#### F2.3 — Phase 2 Validation
- [ ] PTT key works (start/stop capture)
- [ ] Whisper transcribes correctly
- [ ] Full pipeline: speech → text → LLM → JSON → game action

---

### PHASE 3: TTS Squad Feedback (Optional)
**Goal**: squad members "speak" their observations out loud via TTS.

- [ ] Research TTS engine (Piper, XTTS, or Coqui)
- [ ] Integrate TTS into the Python bridge
- [ ] `voice_reply` field from LLM JSON → audio playback
- [ ] Radio-style audio in game (via `say3D` or external audio channel)

---

## 5. GUARDRAILS

These guardrails make the system fail-safe; the operator should never need manual
intervention on errors.

### 5.1 JSON Validation
- **Python**: all incoming JSON from Reforger is validated with Pydantic models. Invalid JSON = HTTP 422 + fallback response `{action: "HOLD", voice_reply: "Invalid data received"}`
- **Python**: all outgoing JSON to Reforger is validated against the function calling schema. Invalid LLM output = retry with stricter prompt or fallback HOLD
- **Enforce Script**: all incoming JSON from Python is parsed defensively. Parse failure = log + ignore (no crash)

### 5.2 Timeout Handling
- **LLM call timeout**: 3 seconds. On timeout → fallback command `{action: "HOLD", voice_reply: "Command timeout, holding position"}`
- **REST call timeout (Enforce Script)**: 5 seconds. On timeout → log + passive mode for 10 seconds, then retry
- **Health check retry**: 3 attempts with 2s interval at startup. Then passive mode

### 5.3 Rate Limiting
- **SITREP frequency**: max 1 per 10 seconds (configurable in `config.json`)
- **LLM call frequency**: max 1 per 2 seconds to prevent spam/loops
- **Queue**: if an LLM call is in flight, new requests are queued (max queue: 3, then drop oldest)

### 5.4 Error Handling
- **Python**: all exceptions are logged to `bridge.log` with timestamp. The server never crashes — FastAPI error handlers catch everything
- **Enforce Script**: all `RestCallback` errors are logged via `Print()`. No `throw`. The script keeps running in passive mode
- **Proxy unavailable**: Python detects this, returns fallback to game, logs error

### 5.5 Passive Mode
- If the Python server is not running at game startup → mod loads in passive mode (no LLM calls, squad behaves as standard AI)
- If the proxy is unreachable → Python returns HOLD commands, logs errors, retries every 30s
- Operator does not need to restart the game when Python/proxy comes back online — the next SITREP cycle detects it automatically

### 5.6 Configuration
All settings in one `python_bridge/config.json` (GITIGNORED — template: `config.example.json`):
```json
{
  "server": { "host": "127.0.0.1", "port": 5001 },
  "llm": {
    "base_url": "http://192.168.1.35:11434/v1",
    "api_key": "<see python_bridge/config.json — never commit>",
    "model": "llama3",
    "timeout_seconds": 10,
    "max_tokens": 300
  },
  "game": {
    "sitrep_interval_seconds": 10,
    "squad_names": ["ALPHA", "BRAVO", "CHARLIE"],
    "fallback_action": "HOLD"
  },
  "voice": {
    "enabled": false,
    "ptt_key": "F24",
    "whisper_model": "small",
    "whisper_device": "cpu",
    "whisper_compute_type": "int8"
  },
  "logging": { "level": "INFO", "file": "bridge.log" }
}
```

### 5.7 Operator Guardrails
Things the operator does NOT have to do — the agent handles these:

| Task | Who | How |
|---|---|---|
| Create Python venv | Agent | `python -m venv` in project dir |
| Install dependencies | Agent | `pip install -r requirements.txt` |
| Generate config file | Agent | writes `config.json` from `config.example.json` with correct proxy URL + key |
| Mod directory structure | Agent | creates all folders + `.c` files + `addon.gproj` |
| Write test scripts | Agent | `test_client.py` for standalone testing |
| Launch parameter docs | Agent | documentation in README/MOD_SETUP |
| Read error logs | Agent | Goose reads `bridge.log` / `console.log` when problems occur |

Things the operator DOES have to do:

| Task | Why |
|---|---|
| Start the game via `launch_reforger.bat` | the game does not run inside goose's process space |
| Press the microphone key (PTT) | physical hardware interaction |
| Load an in-game scenario | game UI interaction |
| Keep proxy/llama-server running | external machine (`192.168.1.35`) |

---

## 6. DELIVERABLES PER PHASE

### Phase 1 Deliverables
| # | File | Description |
|---|---|---|
| 1 | `python_bridge/main.py` | FastAPI server with /health, /sitrep, /command endpoints |
| 2 | `python_bridge/config.json` | Central configuration (gitignored; template `config.example.json`) |
| 3 | `python_bridge/requirements.txt` | Python dependencies |
| 4 | `python_bridge/test_client.py` | Standalone test script (no game needed) |
| 5 | `reforger_mod/addons/ReforgerLLMSquad/Scripts/Game/LLMBridge.c` | Enforce Script REST bridge + AI control |
| 6 | `reforger_mod/addons/ReforgerLLMSquad/addon.gproj` | Mod project file (own GUID) |
| 7 | `README.md` | Install & usage instructions |

### Phase 2 Deliverables
| # | File | Description |
|---|---|---|
| 8 | `python_bridge/voice_handler.py` | Whisper STT + PTT listener |
| 9 | Update `python_bridge/main.py` | add `/voice` endpoint |
| 10 | Update `python_bridge/config.json` | voice settings activated |
| 11 | Update `python_bridge/requirements.txt` | faster-whisper, sounddevice deps |

---

## 7. TECHNICAL DECISIONS

### 7.1 Model Choice
- **Phase 1**: `llama3` (3B) — 335ms latency, function calling confirmed. Fast enough for real-time squad control.
- **Phase 2**: possible upgrade to `qwen3.6-35b-fast` for more complex speech interpretation, with `llama3` as speed fallback.
- **Configurable**: model is set in `config.json`; the operator can change it without touching code.

### 7.2 Function Calling vs JSON Mode
- **Preference**: function calling (`tools` + `tool_choice`) — guaranteed structured output, no parsing needed.
- **Fallback**: if function calling fails for a specific model, switch to `response_format: json_object` with a strict system prompt.
- **Tested**: `llama3` with function calling works and returns correct `tool_calls` in 335ms.

### 7.3 Mod Loading Mechanism
- The mod loads as an **unpacked addon directory** (no Workshop).
- Reforger has NO `-mod`; local mods load via `-addonsDir <path>` + `-addons <GUID>` (wiki: Arma_Reforger:Startup_Parameters).
- The game compiles `.c` files at runtime from the mod directory.
- Structure: the mod folder must contain `addon.gproj` plus `Scripts/Game/` with the `.c` files.

### 7.4 Enforce Script Constraints (learned from SampleMods + the 2026-08-07 session)
- Use `modded class` syntax to extend existing game classes.
- Components derive from `SCR_BaseGameModeComponent` or `ScriptComponent`.
- `RestContext` and `RestCallback` are native Enfusion classes for HTTP — via
  `GetGame().GetRestApi().GetContext(url)`; never `ref RestContext` (private destructor).
- No `World.GetGameTime()` — accumulate your own time via `timeslice`.
- `SCR_AIGroup` is the container for AI squad units.
- `Print()` for logging (appears in the game `.log` file).
- No `throw` — Enforce Script has no exception handling. Everything via return codes and null checks.
- Full rules: `docs/skills/enforce-script.md`.

---

## 8. RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|---|---|---|
| Enforce Script API not fully documented | code does not compile in game | Failsafe: mod loads in passive mode on script errors. Goose reads logs for debugging. |
| Mod loading fails without Workbench | mod not loaded by game | Verified working 2026-08-07 via `-addonsDir`/`-addons` + correct working dir. |
| LLM hallucinates invalid grid/action | squad performs unwanted actions | JSON schema enforcement via function calling. Python validates action/grid enums. Unknown grid = HOLD fallback. |
| Proxy machine goes down | no LLM responses | Passive mode, HOLD fallback, auto-retry every 30s |
| Latency too high for real-time control | squad reacts slowly | `llama3` (3B) as primary model — 335ms tested. SITREP interval configurable. |
| Game update breaks mod API | script does not compile | Mod uses `modded class` overrides, fairly robust against minor updates. Logs show compile errors. |

---

## 9. EXECUTION TIMELINE

### This Weekend (Phase 1 complete)
1. **Agent writes all Phase 1 deliverables** (main.py, config.json, requirements.txt, test_client.py, LLMBridge.c, addon.gproj, README.md)
2. **Agent creates Python venv** and installs dependencies
3. **Agent runs standalone test** (test_client.py) to validate the LLM pipeline
4. **Operator starts the game** via `launch_reforger.bat`
5. **Operator & agent validate** in-game that the SITREP bridge works

### Next Week (Phase 2)
1. Agent installs `faster-whisper` + `sounddevice`
2. Agent writes `voice_handler.py`
3. Operator tests the voice pipeline

### After That (Phase 3, optional)
1. TTS engine selection and integration
2. Audio playback in game

---

## 10. APPROVAL

**Operator**: read this plan. If you agree, say "go" and I will build out Phase 1 completely —
all files, venv, dependencies, and the standalone test.

If you want changes, mark them and I will adjust the plan before building.
