# Architecture Overview

> High-level system architecture for the Reforger LLM WarSim project.
> See also: [Data Flow](data-flow.md) for detailed request/response diagrams.

---

## System at a Glance

The project connects an Arma Reforger game server to an LLM via a local Python bridge.
There are three logical layers, each with distinct responsibilities:

```
┌─────────────────────────────────────────────────────────────┐
│                      GAME LAYER                              │
│  Arma Reforger Dedicated Server                             │
│  Enforce Script mod "ReforgerLLMSquad"                      │
│  ┌─────────────────┐  ┌──────────────────┐                   │
│  │ Tactical Brain  │  │ Strategic Brain  │                   │
│  │ (BLUFOR C2)     │  │ (OPFOR Stavka)   │                   │
│  └────────┬────────┘  └────────┬─────────┘                   │
│           │   REST (HTTP)       │                             │
└───────────┼─────────────────────┼─────────────────────────────┘
            │                     │
            ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    BRIDGE LAYER                              │
│  Python 3.11 + FastAPI + uvicorn                            │
│  127.0.0.1:5001                                             │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ REST Routes  │  │ Pydantic Schemas │  │ OpenAI Client │  │
│  │ /sitrep      │  │ (JSON validation)│  │ (LLM adapter) │  │
│  │ /orders      │  │                  │  │               │  │
│  │ /command     │  │                  │  │               │  │
│  └──────────────┘  └──────────────────┘  └───────┬───────┘  │
└────────────────────────────────────────────────────┼──────────┘
                                                     │
                                                     ▼
┌─────────────────────────────────────────────────────────────┐
│                      LLM LAYER                               │
│  Ollama-compatible Proxy (LAN)                              │
│  http://192.168.1.35:11434/v1                              │
│  Model: llama3 (8B)                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 1: Game Layer (Enforce Script Mod)

### What it is

The `ReforgerLLMSquad` addon runs inside the Arma Reforger game engine via Enforce Script.
It is loaded on the **dedicated server** (not just the client), which is critical for
AI spawning, faction management, and group control.

### Addon structure

```
reforger_mod/addons/ReforgerLLMSquad/
├── addon.gproj          # GameProject metadata (NOT addon.json — that does not exist)
├── Scripts/
│   └── Game/
│       ├── LLMBridge.c          # REST client + callback handler
│       ├── LLMSquadGameMode.c   # (planned) modded SCR_BaseGameMode
│       ├── LLMSquadController.c  # (planned) modded SCR_PlayerController hook
│       └── ...
└── config.json         # GITIGNORED — runtime config (copy from config.example.json)
```

### Key classes (planned)

| Class | Responsibility |
|---|---|
| `LLMBridge` | HTTP REST client. Uses `GetGame().GetRestApi().GetContext(url)` + `GET(cb, path)` / `POST(cb, path, body)`. Handles `RestCallback` for async responses. |
| `LLMSquadGameMode` (modded `SCR_BaseGameMode`) | Instantiates `LLMBridge`, runs `Update()` via `GetGame().GetCallqueue().CallLater()`. |
| `LLMSquadController` (modded `SCR_PlayerController`) | Hooks `OnControlledEntityChanged()` for player spawn detection → auto-squad creation. |

### Two-brain design

The mod hosts two independent AI "brains" running at different cadences:

#### Tactical Brain (BLUFOR)

- **Faction**: BLUFOR (player's faction, typically US)
- **Trigger**: Player sends a text command (chat or REST)
- **Latency target**: 2–5 seconds (fast, responses for active gameplay)
- **Scope**: Squad-level — manages individual waypoints, formations, stances
- **Authority**: Rank-checked (CAPTAIN > SERGEANT > AI autonomous)
- **Cannot touch**: OPFOR groups (namespace isolation)

#### Strategic Brain (OPFOR Stavka)

- **Faction**: OPFOR (enemy faction, typically Soviet)
- **Trigger**: Timer — reads full WorldState every 60–120 seconds
- **Latency target**: 60–120 seconds (slow, deliberate strategic decisions)
- **Scope**: Theatre-level — spawns OPFOR groups, assigns objectives (SEIZE/DEFEND/REINFORCE)
- **Authority**: Highest — Stavka OPORDs override BLUFOR tactical orders in priority stack
- **Cannot touch**: BLUFOR groups (namespace isolation)

### REST transport (Enforce Script side)

Enforce Script's REST API is **callback-based and async**. There is no synchronous
`fetch()` or blocking HTTP. The pattern:

```c
// 1. Get REST API and create a context
RestContext ctx = GetGame().GetRestApi().GetContext("http://127.0.0.1:5001");

// 2. Define a callback class
class LLMBridgeCallback : RestCallback
{
    override void OnSuccess(string data, int dataSize) { /* handle response */ }
    override void OnError(int errorCode) { /* handle error */ }
    override void OnTimeout() { /* handle timeout */ }
}

// 3. Issue the request (non-blocking)
LLMBridgeCallback cb = new LLMBridgeCallback();
ctx.POST(cb, "/sitrep", jsonBodyString);
// or
ctx.GET(cb, "/orders");
```

> **Anti-hallucination**: `new RestContext()`, `SetURL()`, `SetMethod()`, `SetBody()`,
> `Start()` do NOT exist in Reforger's Enforce Script. See
> [Verified API](../api/enforce-script-verified.md) and
> [Engine Constraints](../reference/constraints.md).

---

## Layer 2: Bridge Layer (Python FastAPI)

### What it is

A lightweight FastAPI application that:
1. Receives REST requests from the game mod
2. Validates JSON payloads using Pydantic schemas
3. Translates game state into LLM prompts
4. Calls the LLM via the OpenAI Python client (compatible with Ollama)
5. Returns LLM-generated commands back to the game

### Stack

| Component | Version / Path |
|---|---|
| Python | 3.11 |
| Web framework | FastAPI |
| Server | uvicorn |
| Validation | Pydantic |
| LLM client | `openai` Python package (Ollama-compatible) |
| Entry point | `python_bridge/main.py` |
| Config | `python_bridge/config.json` (GITIGNORED — copy from `config.example.json`) |
| Port | 5001 |
| Launch | `start_bridge.bat` |

### Key endpoints

| Method | Path | Direction | Purpose |
|---|---|---|---|
| POST | `/sitrep` | Game → Bridge | Periodic world state report (squad positions, enemy contacts, objectives) |
| GET | `/orders` | Bridge → Game | Game polls for pending commands (JSON array) |
| POST | `/command/result` | Game → Bridge | Feedback on command execution (success/failure) |
| POST | `/waypoint` | Game → Bridge | Direct waypoint submission (known gap: missing in main.py) |
| GET | `/status` | Game → Bridge | Health check (known mismatch: GET in main.py, POST in LLMBridge.c) |

> See [REST Contracts](../api/rest-contracts.md) for full endpoint specifications.

### Known configuration gaps (F1.3)

1. `/waypoint` endpoint exists in `LLMBridge.c` but not in `main.py`
2. `/status` is `GET` in `main.py` but `POST` in `LLMBridge.c`
3. These must be synchronized before e2e testing

---

## Layer 3: LLM Layer (Ollama Proxy)

### What it is

An Ollama-compatible proxy running on the LAN at `http://192.168.1.35:11434/v1`.
The bridge connects to it using the standard OpenAI Python client, making it compatible
with any OpenAI-API-compatible endpoint.

### Configuration

```json
{
  "llm_base_url": "http://192.168.1.35:11434/v1",
  "llm_model": "llama3",
  "llm_api_key": "ollama"
}
```

### Model considerations

| Brain | Model | Why |
|---|---|---|
| Tactical (BLUFOR) | `llama3` (8B) | Fast inference, sufficient for tactical waypoint JSON generation |
| Strategic (Stavka) | `llama3` (8B) or larger | Strategic reasoning may benefit from larger context; verify available models on proxy |

### Fallback behavior

| Scenario | Tactical behavior | Strategic behavior |
|---|---|---|
| Bridge unreachable | HOLD position (vanilla AI) | Maintain previous OPORD |
| LLM timeout (>3s tactical, >30s strategic) | HOLD position | Maintain previous OPORD |
| LLM returns invalid JSON | HOLD position | Maintain previous OPORD |

---

## Data Flow Summary

```
Player Command ──→ Enforce Script ──→ POST /sitrep ──→ FastAPI Bridge
                                                              │
                                                              ▼
                                                    LLM (llama3 via Ollama)
                                                              │
                                                              ▼
                                          JSON Command ←──────┘
                                                              │
Game ←── SCR_AIGroup.AddWaypointToGroup() ←── GET /orders ←────┘
```

For detailed flow diagrams, see [Data Flow](data-flow.md).

---

## Current Status (as of 2026-08-08)

| Milestone | Status | Description |
|---|---|---|
| F0 | ✅ DONE | Mod loads in game, scripts compile |
| F1.1 | ✅ DONE | Game reaches main menu (verified via console.log) |
| F1.2 | 🔲 NEXT | Component wiring — `SCR_PlayerController` hook, auto-squad spawn, `LLMBridge` instantiation via `CallLater()` |
| F1.3 | 🔲 TODO | Route sync game↔bridge (`/waypoint`, `/status`), e2e JSON validation |
| F2.x | 🔲 TODO | Tactical C2 — WorldState reporter, LLM tactical router, waypoint execution |
| F3.x | 🔲 TODO | Strategic Stavka — OPORFOR orchestration, feedback loop |
| F4.x | 🔲 TODO | Full WarSim — LLM vs LLM, radio, TTS, persistent campaign |

See [Phased Roadmap](../roadmap/phases.md) for the full plan.

---

## Design Principles

1. **Empirical testing**: Every change is verified by kill → launch → check log. No assumptions.
2. **Namespace isolation**: BLUFOR and OPFOR AI brains never touch each other's groups.
3. **Graceful degradation**: If the bridge or LLM is down, the game falls back to vanilla AI — no crash.
4. **Anti-hallucination**: All API calls are verified against Doxygen docs or extracted mod source. See [Engine Constraints](../reference/constraints.md).
5. **Conservative spawning**: `AIWorld.SetAILimit()` prevents runaway AI population.
6. **English everywhere**: Code, comments, docs, commits.
