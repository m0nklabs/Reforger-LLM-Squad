# Reforger LLM Squad Control

LLM-driven squad control for Arma Reforger. An Enforce-script mod in the game talks over
HTTP to a local FastAPI bridge, which forwards requests to an LLM (Ollama-compatible proxy).
The LLM issues tactical orders, AI soldiers execute them, and OPFOR strategic AI adapts.

## Features

- **AI Squad**: 5 BLUFOR AI soldiers auto-spawn, follow the player, execute LLM orders
- **LLM Tactical AI**: SITREP → LLM → ENGAGE/HOLD/MOVE/FLANK/RETREAT/MOUNT/DISMOUNT
- **OPFOR Strategic AI (Stavka)**: LLM decides enemy strategy (spawn, flank, hold, reinforce)
- **Voice (Phase 2)**: Push-to-talk → Whisper STT → LLM → squad orders
- **TTS (Phase 3)**: Squad "speaks" voice replies via edge-tts (10 distinct voices)
- **Environment Awareness**: Time of day, day/night, terrain elevation in SITREP
- **Enemy Detection**: BLUFOR reports OPFOR positions, LLM adapts tactics
- **Player Gating**: No LLM activity when 0 players on server

## Architecture

```text
┌─────────────────┐    HTTP     ┌──────────────────┐    HTTP    ┌──────────────┐
│  Arma Reforger  │ <─────────> │  Python Bridge   │ <────────> │  LLM Proxy   │
│  (DS + mod)     │   GET ?data │  FastAPI :5001   │  OpenAI    │  192.168.    │
│                 │             │                  │  SDK       │  1.35:11434  │
│  LLMBridge.c    │             │  main.py         │            │              │
│  AutoSquadMgr.c │             │  voice_handler.py│            │  llama3.2-3b │
│  StavkaCtrl.c   │             │  tts_handler.py  │            │              │
└─────────────────┘             └──────────────────┘            └──────────────┘
        │                               │
        │ RPL (MP networking)           │ edge-tts (speakers)
        v                               v
  Game Client (127.0.0.1:2001)   Audio output
```

## Quick Start

### 1. Start the Python bridge
```batch
start_bridge.bat
```
Auto-elevates to admin (needed for PTT key listener). Runs on port 5001.

### 2. Start the Dedicated Server
```batch
taskkill /F /IM ArmaReforgerServer.exe
launch_ds.bat
```
DS compiles the mod and hosts the game. Mod loads from BI Workshop cache.

### 3. Connect game client
Launch Arma Reforger → Multiplayer → Direct Connect → `127.0.0.1:2001`

### 4. Verify
```batch
powershell -NoProfile -File scripts\check_latest_log.ps1
```
Should report `OK: mod loaded, no compile errors`.

### 5. Play
- Join a group (e.g. Atlas Red 1) in the game
- AutoSquad spawns AI soldiers within ~10-60s (retry logic handles group-join delay)
- AI squad follows you, SITREPs flow to LLM every 30s
- Use the radial menu (Commanding) for vehicle commands, or voice/text for LLM orders

## File Paths

### Project Directory
```
Q:\GAMES\Reforger-LLM-Squad\
├── reforger_mod\addons\ReforgerLLMSquad\    ← MOD SOURCE (edit here)
│   ├── addon.gproj                           ← GUID: 7E5A1C9B3D8F2406
│   └── Scripts\Game\
│       ├── LLMBridge.c                       ← REST bridge + SITREP + waypoints
│       ├── AutoSquadManager.c               ← AI spawn, group, vehicle mount
│       ├── StavkaController.c               ← OPFOR strategic AI
│       ├── SCR_BaseGameMode_Component.c     ← Game mode + player gating
│       ├── LLMAutoConnect.c                 ← Auto-connect to DS
│       └── AutoConnectMenu.c                ← Modded ServerBrowser
├── python_bridge\
│   ├── main.py                               ← FastAPI bridge (all endpoints)
│   ├── voice_handler.py                      ← Whisper STT + PTT
│   ├── tts_handler.py                        ← edge-tts + pyttsx3
│   ├── test_client.py                        ← 9-test suite
│   ├── config.json                           ← GITIGNORED (copy from example)
│   └── config.example.json                   ← Template config
├── launch_ds.bat                             ← DS launcher
├── launch_reforger.bat                       ← Game client launcher (listen server)
├── start_bridge.bat                          ← Bridge launcher (auto-elevate)
└── scripts\check_latest_log.ps1              ← Log checker
```

### Game / Server Paths
| Item | Path |
|---|---|
| Game client | `Q:\SteamLibrary\steamapps\common\Arma Reforger\` |
| Dedicated Server | `Q:\SteamLibrary\steamapps\common\Arma Reforger Server\` |
| DS server.json | `Q:\SteamLibrary\steamapps\common\Arma Reforger Server\server.json` |
| Mod (DS local) | `Q:\SteamLibrary\steamapps\common\Arma Reforger Server\addons\ReforgerLLMSquad\` |
| Mod (Workshop cache) | `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\ReforgerLLMSquadControl_7E5A1C9B3D8F2406\` |
| Game/DS logs | `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<timestamp>\console.log` |

### Sync Workflow (after editing mod source)
When you edit `.c` files, you MUST sync to 3 locations:
```batch
REM From project root:
copy /Y "reforger_mod\addons\ReforgerLLMSquad\Scripts\Game\<file>.c" ^
  "Q:\SteamLibrary\steamapps\common\Arma Reforger Server\addons\ReforgerLLMSquad\Scripts\Game\<file>.c"

copy /Y "reforger_mod\addons\ReforgerLLMSquad\Scripts\Game\<file>.c" ^
  "C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\ReforgerLLMSquadControl_7E5A1C9B3D8F2406\Scripts\Game\<file>.c"
```
The Workshop cache overrides the DS local addons — if you don't sync there, the DS compiles the OLD version!

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Bridge health (uptime, LLM calls, TTS status) |
| GET | `/sitrep?data=<json>` | Game sends SITREP, gets LLM tactical order back |
| GET | `/command?data=<json>` | Operator text command → LLM order |
| GET | `/orders` | Game polls for queued commands |
| POST | `/orders` | Queue a command (spawn, mount, move, etc.) |
| GET | `/ai_thought` | Game polls for AI personality thoughts |
| GET | `/stavka?opfor=N` | Game polls for OPFOR strategic orders |
| GET | `/voice` | Voice handler status |
| GET | `/tts` | TTS handler status |

## Configuration

Copy `python_bridge/config.example.json` to `python_bridge/config.json`:
```json
{
  "server": { "host": "127.0.0.1", "port": 5001 },
  "llm": {
    "base_url": "http://192.168.1.35:11434/v1",
    "api_key": "<your-key>",
    "model": "llama3.2-3b",
    "timeout_seconds": 10
  },
  "voice": {
    "enabled": true, "ptt_key": "F24",
    "whisper_model": "tiny", "whisper_device": "cpu"
  },
  "tts": { "enabled": true, "engine": "auto" }
}
```

## Testing

```bash
cd python_bridge
python test_client.py          # All 9 tests
python test_client.py health   # Just health
python test_client.py tts      # Just TTS check
```

## Performance

- **LLM latency**: ~520ms average (llama3.2-3b)
- **SITREP interval**: 30s (configurable)
- **Stavka poll**: 60s + casualty-triggered early poll
- **AI thoughts**: 30s poll, deduplicated

## Documentation

- **AGENTS.md** — Canonical AI-agent context (source of truth, read first)
- **MOD_SETUP.md** — Launch error diagnosis + verified fix
- **AGENTS.md** — Canonical project context, rules & roadmap (source of truth)
- **docs/dedicated-server-setup.md** — DS configuration details
- **docs/skills/** — Enforce Script, modding, debugging lessons

## Status

| Feature | Status | Description |
|---|---|---|
| F1: REST Bridge | ✅ Done | Game↔bridge↔LLM, all endpoints synced |
| F2: AI Squad | ✅ Done | Spawn, follow, formation, live orders |
| F3.1-3.3: Stavka | ✅ Done | OPFOR strategic AI + feedback loop |
| F3.4: Enemy Detection | ✅ Done | SITREP reports OPFOR, LLM ENGAGE |
| F3.5: Environment | ✅ Done | Time/day-night/elevation in SITREP |
| Phase 2: Voice | ✅ Done | Whisper STT + PTT + /voice endpoint |
| Phase 3: TTS | ✅ Done | edge-tts + pyttsx3, 9/9 tests pass |
| F4: Vehicles | ✅ Done | MOUNT/DISMOUNT commands (vanilla radial also works) |
| Auto-connect | ✅ Done | Modded ServerBrowser auto-join DS |
| Player gating | ✅ Done | No LLM when 0 players |

## License

Open-source. See repository for details.
