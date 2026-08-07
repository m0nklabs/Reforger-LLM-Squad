# Workflow Summary - Reforger LLM Squad Control

## Overview
This project implements an LLM-driven squad control system for Arma Reforger using a REST bridge between the game (Enforce script) and a local FastAPI server (Python).

## Architecture
```
OPERATOR → [Arma Reforger] → HTTP/JSON → [Python Bridge FastAPI :5001] → HTTP/OpenAI → [LLM Proxy :11434/v1]
              LLMBridge.c                        main.py                                  llama3
              SCR_BaseGameMode_Component.c
```

## Development Workflow
1. **Edit Enforce scripts** → `reforger_mod/addons/ReforgerLLMSquad/Scripts/Game/*.c`
2. **Edit Python bridge** → `python_bridge/main.py`
3. **Test Python locally** → `python test_client.py` (5 tests)
4. **Start Python bridge** → `start_bridge.bat` (port 5001)
5. **Kill old game** → `taskkill /F /IM ArmaReforgerSteam.exe`
6. **Launch game with mod** → `launch_reforger.bat`
7. **Wait 50s** → Check `console.log` with `check_latest_log.ps1`

## Key Files
| File | Purpose |
|------|---------|
| `reforger_mod/addons/ReforgerLLMSquad/Scripts/Game/LLMBridge.c` | REST client to Python bridge |
| `reforger_mod/addons/ReforgerLLMSquad/Scripts/Game/SCR_BaseGameMode_Component.c` | GameMode component wiring |
| `reforger_mod/addons/ReforgerLLMSquad/addon.gproj` | Mod definition |
| `python_bridge/main.py` | FastAPI server with LLM proxy |
| `python_bridge/config.json` | Local config (gitignored) |
| `python_bridge/config.example.json` | Config template |
| `python_bridge/test_client.py` | Standalone test suite |

## Testing
### Python Bridge Tests (5/5 passed)
- Health Check: Verifies server is responsive
- SITREP Bridge: Test LLM response to telemetry
- Operator Command: Test LLM response to text commands
- Latency: Measure round-trip performance (~599ms average)
- Error Handling: Verify invalid data returns 422

### Game Tests
- Scripts compile without errors (only base-game deprecation warnings)
- Mod loads with correct GUID `7E5A1C9B3D8F2406`
- Game reaches main menu successfully
- OnGameStart hook implemented in SCR_BaseGameMode_Component.c

## Critical Rules (from AGENTS.md)
1. Use `-addonsDir <path> -addons <GUID>`, NOT `-mod=`
2. Always start game with working directory = game dir
3. GUID `58D0FB3206B6F859` = base game; `7E5A1C9B3D8F2406` = our mod
4. Never commit `config.json` (secrets protection)
5. Use `override` keyword only for methods that exist in base class

## Next Steps
- F1.5 Phase 1 Validation: Start scenario in-game to trigger OnGameStart
- Add `ref` keyword to Enforce REST callback variables (deprecated API compatibility)
