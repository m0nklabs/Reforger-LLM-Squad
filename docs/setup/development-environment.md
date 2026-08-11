# Development Environment

> Tools, paths, and setup for developing the Reforger LLM WarSim project.

---

## Directory Structure

```
Q:\GAMES\Reforger-LLM-Squad\              ← Project root
├── reforger_mod\
│   └── addons\
│       └── ReforgerLLMSquad\             ← Our Enforce Script mod
│           ├── addon.gproj               ← GameProject metadata
│           └── Scripts\
│               └── Game\
│                   ├── LLMBridge.c       ← REST client
│                   └── ...               ← Other script files
├── python_bridge\
│   ├── main.py                           ← FastAPI bridge entry point
│   ├── config.json                       ← GITIGNORED (copy from config.example.json)
│   └── config.example.json               ← Template config
├── docs\                                 ← This documentation set
├── scripts\
│   ├── check_latest_log.ps1             ← Log verification script
│   ├── sync-agent-docs.bat              ← Sync AGENTS.md → CLAUDE.md, .goosehints
│   ├── rcon_test.py                     ← RCON client test (berconpy)
│   ├── launch_reforger.bat              ← Game client + mod launcher
│   └── start_bridge.bat                 ← Python bridge launcher
├── tools\
│   ├── ds1874900\                        ← Dedicated server directory
│   ├── server_profile\                   ← Server profile (logs, addons)
│   ├── PakInspector.exe                 ← .pak file extractor
│   └── aac_extracted\                   ← AAC mod source (reference, gitignored)
├── AGENTS.md                             ← Canonical AI-agent context (source of truth)
├── MOD_SETUP.md                          ← Launch diagnosis document
└── AGENTS.md                       ← Project context, rules & roadmap
```

---

## Development Tools

### Arma Reforger Workbench

| Property | Value |
|---|---|
| Executable | `Q:\SteamLibrary\steamapps\common\Arma Reforger Tools\Workbench\ArmaReforgerWorkbenchSteamDiag.exe` |
| Purpose | Visual scripting, world editing, addon packaging, resource management |
| Usage | Launch from Steam → "Arma Reforger Tools" → Workbench |

The Workbench is the official tool for:
- Creating and editing Enforce Script addons
- Packaging `.pak` files for distribution
- World/mission editing
- Resource management (models, textures, sounds)

### Doxygen API Documentation

| Property | Value |
|---|---|
| Archive | `Q:\SteamLibrary\steamapps\common\Arma Reforger Tools\Workbench\docs\ArmaReforgerScriptAPIPublic.zip` |
| Size | 98 MB |
| Entries | 29,234 |
| Format | Doxygen HTML |
| Purpose | Complete Enforce Script API reference — every class, method, and property |

**Usage:**

```cmd
# Extract the Doxygen docs:
cd Q:\SteamLibrary\steamapps\common\Arma Reforger Tools\Workbench\docs
powershell -Command "Expand-Archive ArmaReforgerScriptAPIPublic.zip -DestinationPath .\ExtractedAPI"

# Search for a class or method:
findstr /S /I " SCR_AIGroup " .\ExtractedAPI\*.html
```

> When writing Enforce Script, ALWAYS verify method signatures against the Doxygen docs.
> See [Enforce Script Verified API](../api/enforce-script-verified.md) for pre-verified signatures.

### PakInspector

| Property | Value |
|---|---|
| Path | `Q:\GAMES\Reforger-LLM-Squad\tools\PakInspector.exe` |
| Source | [github.com/rvost/PakInspector](https://github.com/rvost/PakInspector) |
| Purpose | Extract `.pak` files to inspect mod source code |

**Usage:**

```cmd
# Extract a mod's .pak file:
tools\PakInspector.exe extract --input "<path_to_mod.pak>" --output tools\extracted\

# Example: Extract AAC mod for reference:
tools\PakInspector.exe extract --input "C:\...\aac_addon.pak" --output tools\aac_extracted\
```

> The extracted AAC source is in `tools/aac_extracted/Scripts/Game/` and contains 13 `.c` files.
> See [AAC Mod Analysis](../api/aac-mod-analysis.md) for details.

### AAC Extracted Source (Reference)

| Property | Value |
|---|---|
| Location | `Q:\GAMES\Reforger-LLM-Squad\tools\aac_extracted\Scripts\Game\` |
| File count | 13 `.c` source files |
| Source mod | Advanced AI Command (GUID 69A404653EE3F3C4, v1.0.2) |
| Status | Gitignored (reference only, not committed) |

This extracted source serves as a reference for proven AI management patterns in
Arma Reforger. See [AAC Mod Analysis](../api/aac-mod-analysis.md) for the full analysis.

---

## Game Paths

| Component | Path |
|---|---|
| Game installation (client) | `Q:\SteamLibrary\steamapps\common\Arma Reforger` |
| Game executable | `Q:\SteamLibrary\steamapps\common\Arma Reforger\ArmaReforgerSteam.exe` |
| Game addons | `Q:\SteamLibrary\steamapps\common\Arma Reforger\addons\` |
| Base game project | `Q:\SteamLibrary\steamapps\common\Arma Reforger\addons\data\ArmaReforger.gproj` |
| Server installation | `Q:\GAMES\Reforger-LLM-Squad\tools\ds1874900` |
| Server executable | `Q:\GAMES\Reforger-LLM-Squad\tools\ds1874900\ArmaReforgerServer.exe` |
| Server profile | `Q:\GAMES\Reforger-LLM-Squad\tools\server_profile` |
| Server addons | `Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\addons\` |
| Server logs | `Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_<timestamp>\console.log` |
| Client profile | `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger` |
| Client logs | `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<timestamp>\console.log` |

---

## Python Bridge

| Property | Value |
|---|---|
| Entry point | `python_bridge/main.py` |
| Python version | 3.11 |
| Framework | FastAPI |
| Server | uvicorn |
| Dependencies | fastapi, uvicorn, pydantic, openai |
| Port | 5001 |
| Config | `python_bridge/config.json` (GITIGNORED — copy from `config.example.json`) |
| Launcher | `start_bridge.bat` |

### Setting up the bridge

```cmd
# 1. Create virtual environment
cd Q:\GAMES\Reforger-LLM-Squad\python_bridge
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies
pip install fastapi uvicorn pydantic openai

# 3. Copy config template
copy config.example.json config.json

# 4. Edit config.json with your settings (API key, model, etc.)

# 5. Start the bridge
cd Q:\GAMES\Reforger-LLM-Squad
start_bridge.bat
```

### Config file (config.json)

```json
{
    "bridge_host": "127.0.0.1",
    "bridge_port": 5001,
    "llm_base_url": "http://192.168.1.35:11434/v1",
    "llm_model": "llama3",
    "llm_api_key": "ollama",
    "tactical_timeout": 3,
    "strategic_timeout": 30
}
```

> **WARNING**: `config.json` is GITIGNORED and pre-commit blocked. Never commit it.
> Only commit `config.example.json`. See [Engine Constraints](../reference/constraints.md).

---

## LLM Proxy

| Property | Value |
|---|---|
| Endpoint | `http://192.168.1.35:11434/v1` |
| Type | Ollama-compatible proxy (OpenAI API format) |
| Model | `llama3` (8B parameters) |
| Client | Python `openai` package |

### Verifying the LLM proxy

```cmd
# Check if Ollama is running:
curl http://192.168.1.35:11434/api/tags

# Expected response:
# {"models":[{"name":"llama3:latest","modified_at":"...","size":...}]}

# Test a simple completion:
curl http://192.168.1.35:11434/v1/chat/completions ^
    -H "Content-Type: application/json" ^
    -d "{\"model\":\"llama3\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}"
```

### Available models

To check which models are available on the proxy:

```cmd
curl http://192.168.1.35:11434/api/tags
```

If larger models are available (e.g., `llama3:70b`), they may be preferable for the
Strategic Stavka brain (better reasoning, but slower inference).

---

## RCON Client

| Property | Value |
|---|---|
| File | `scripts/rcon_test.py` |
| Library | `berconpy` (async Python BattlEye RCON client) |
| Protocol | BattlEye RCON over TCP |
| Server | `127.0.0.1:19999` |

### Installing berconpy

```cmd
pip install berconpy
```

### Running RCON test

```cmd
cd Q:\GAMES\Reforger-LLM-Squad
python scripts\rcon_test.py
```

---

## Launch Scripts

### start_bridge.bat

Starts the Python FastAPI bridge on port 5001.

```cmd
@echo off
cd /d Q:\GAMES\Reforger-LLM-Squad\python_bridge
python main.py
```

### launch_reforger.bat

Launches the Arma Reforger client with our mod loaded.

```cmd
@echo off
start /d "Q:\SteamLibrary\steamapps\common\Arma Reforger" ^
    ArmaReforgerSteam.exe ^
    -addonsDir "Q:\SteamLibrary\steamapps\common\Arma Reforger\addons" ^
    -addons 7E5A1C9B3D8F2406
```

> **Critical**: The `start /d "<game_dir>"` sets the working directory to the game
> installation. Without this, the engine cannot find the base game addons.

### check_latest_log.ps1

Verifies the latest game log for success/crash indicators.

```powershell
powershell -NoProfile -File scripts\check_latest_log.ps1
```

**Expected output on success:** `OK`
**Expected output on crash:** Error details (log size ~1145 bytes, "Unable to initialize the game")

---

## Sync Scripts

### sync-agent-docs.bat

Syncs `AGENTS.md` to `CLAUDE.md` and `.goosehints` (Windows does not support symlinks
in all contexts, so we maintain copies).

```cmd
scripts\sync-agent-docs.bat
```

> **Mandatory**: Run this after editing `AGENTS.md` before committing. The pre-commit
> hook (`core.hooksPath=.githooks`) blocks commits with drifted copies.

---

## Git Configuration

| Setting | Value |
|---|---|
| Hooks path | `.githooks` (configured via `core.hooksPath`) |
| Pre-commit checks | 1. No secrets in `config.json` 2. No GUID changes in `addon.gproj` 3. AGENTS.md/CLAUDE.md/.goosehints in sync |
| Gitignored | `config.json`, `tools/aac_extracted/`, `tools/server_profile/`, `docs/` (BI sample mods) |

---

## Environment Checklist

Before starting development, ensure all of the following are available:

- [ ] Arma Reforger installed at `Q:\SteamLibrary\steamapps\common\Arma Reforger`
- [ ] Arma Reforger Tools (Workbench) installed
- [ ] Doxygen API docs extracted (from `ArmaReforgerScriptAPIPublic.zip`)
- [ ] Python 3.11 installed
- [ ] Python virtual environment created in `python_bridge/`
- [ ] `config.json` created from `config.example.json`
- [ ] Ollama proxy reachable at `http://192.168.1.35:11434/v1`
- [ ] `llama3` model available on the proxy
- [ ] Dedicated server downloaded to `tools/ds1874900/`
- [ ] `PakInspector.exe` in `tools/`
- [ ] Git hooks configured (`core.hooksPath=.githooks`)
