# Reforger LLM Squad Control

LLM-powered squad control system for Arma Reforger.

## Quick Start

1. **Start the Python bridge:**
   ```
   start_bridge.bat
   ```

2. **Launch Arma Reforger:**
   ```
   launch_reforger.bat
   ```

3. **Verify:**
   ```
   powershell -NoProfile -File scripts\check_latest_log.ps1
   ```
   This checks the newest `console.log`: mod loaded, compile status, error scan, OK/NO-GO verdict.
   Details: `MOD_SETUP.md`.

## Architecture

```text
Game (Enforce Script) <--HTTP--> Python Bridge <--HTTP--> LLM Proxy
     |                                    |                  |
  LLMBridge.c                        main.py           llama3
  (REST bridge)                    (FastAPI)        (192.168.1.35:11434)
```

## Components

### Python Bridge (`python_bridge/`)
- **main.py** - FastAPI server with endpoints:
  - `GET /health` - Health check
  - `POST /sitrep` - Receive SITREP from game
  - `POST /command` - Receive operator command
  - `GET /status` - Bridge status
- **config.json** - Configuration (GITIGNORED — copy from `config.example.json`)
- **test_client.py** - Standalone test suite
- **requirements.txt** - Python dependencies
- **venv/** - Python virtual environment

### Reforger Mod (`reforger_mod/`)
- **addons/ReforgerLLMSquad/Scripts/Game/LLMBridge.c** - Enforce Script component
  - SITREP collection and sending
  - Command routing to LLM
  - Waypoint spawning and execution
  - Radio callbacks
  - Passive mode (HOLD fallback)
- **addon.gproj** - Workbench project file (own GUID `7E5A1C9B3D8F2406`, depends on base game)

## Configuration

Copy `python_bridge/config.example.json` to `python_bridge/config.json` and fill in your
proxy URL + API key. `config.json` is gitignored and must never be committed (pre-commit
hook enforces this).

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 5001
  },
  "llm": {
    "base_url": "http://<LLM-PROXY-HOST>:11434/v1",
    "api_key": "<PUT_YOUR_API_KEY_HERE>",
    "model": "llama3",
    "timeout_seconds": 10
  }
}
```

## Testing

Run the standalone test suite:
```bash
cd python_bridge
venv\Scripts\python.exe test_client.py
```

## API Endpoints

### GET /health
Returns bridge health status.

### POST /sitrep
Receive SITREP from game.
```json
{
  "squad": "ALPHA",
  "grid": "042-081",
  "position_x": 1234.5,
  "position_y": 567.8,
  "position_z": 12.3,
  "health": 85.5,
  "ammo_percent": 62.0,
  "status": "Patrolling",
  "nearby_enemies": 2
}
```

### POST /command
Receive operator command.
```json
{
  "squad": "ALPHA",
  "operator_command": "Move to grid 042-081",
  "current_situation": "Squad ALPHA at grid 042-081"
}
```

## Phases

### Phase 1 (in progress)
- REST bridge + AI squad control
- No voice (text-only)
- Function calling with llama3
- Passive mode on failure
- Status: mod loads & compiles; component wiring (F1.2) still open — see AGENTS.md

### Phase 2 (Next)
- Voice pipeline (Whisper STT -> LLM -> game)
- PTT (push-to-talk) listener
- `/voice` endpoint

### Phase 3 (Future)
- TTS squad feedback
- Voice replies to operator

## Documentation

- **AGENTS.md** — canonical AI-agent context (source of truth, read first)
- **MOD_SETUP.md** — the launch-error diagnosis + verified fix (2026-08-07)
- **PROJECT_PLAN.md** — full architecture & phased plan
- **docs/skills/** — lessons-learned for agents (Reforger modding, Enforce script, debugging)

## Logs

- Bridge logs: `python_bridge/bridge.log`
- Game logs: `My Games\ArmaReforger\logs\logs_<timestamp>\console.log`
- Quick check: `powershell -NoProfile -File scripts\check_latest_log.ps1`
- API docs: http://127.0.0.1:5001/docs
