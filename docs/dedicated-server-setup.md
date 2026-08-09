# Dedicated Server Setup — Arma Reforger LLM Squad

## Status: WORKING (2026-08-09 21:28)

- ✅ DS starts with mod loaded (5637 files)
- ✅ Mod downloaded from BI Workshop via `game.mods[]`
- ✅ Scripts compile and execute on DS (LLMBridge, LLMGameMode, AutoSquad)
- ✅ RPL:2001, RCON:19999, A2S:17777 all active
- ✅ LLM bridge connects to Python bridge on port 5001
- ✅ SITREP + LLM action processing works on DS

## Prerequisites

1. **Mod published to BI Workshop** (even as unlisted) via Arma Reforger Workbench
2. **Python bridge running** on the same machine (port 5001)
3. **server.json** in DS directory with `game.mods[]` containing the addon GUID

## Solution: `game.mods[]` with addon GUID

The `modId` in `game.mods[]` IS the 16-char hex GUID from `addon.gproj` (NOT a Steam numeric ID).
Reforger uses BI's own Workshop at `reforger.armaplatform.com`, not Steam's `publishedfileid`.

### server.json
```json
{
    "bindAddress": "0.0.0.0",
    "a2s": { "address": "0.0.0.0", "port": 17777 },
    "rcon": { "address": "0.0.0.0", "port": 19999, "password": "llmadmin" },
    "game": {
        "name": "LLM Squad Test Server",
        "password": "",
        "scenarioId": "{ECC61978EDCC2B5A}Missions/23_Campaign.conf",
        "maxPlayers": 10,
        "mods": [
            { "modId": "7E5A1C9B3D8F2406", "name": "Reforger LLM Squad Control" }
        ]
    }
}
```

### Launch command
```bat
ArmaReforgerServer.exe -config server.json -nographics -logLevel normal
```

Or use `launch_ds.bat` from the repo root.

## DS startup flow (verified 2026-08-09)

1. DS starts, loads vanilla (5633 files, core + data)
2. DS reads `game.mods[]`, finds modId `7E5A1C9B3D8F2406`
3. DS contacts BI Workshop, downloads mod (`.pak` + `resourceDatabase.rdb`)
4. DS reloads with mod (5637 files — 4 extra = our scripts)
5. Scripts compile: `LLMBridge.c`, `AutoSquadManager.c`, `SCR_BaseGameMode_Component.c`
6. `[LLMGameMode] EOnInit FIRED — modded SCR_BaseGameMode is alive`
7. `[LLMGameMode] OnGameStart - Initializing LLM Bridge`
8. RPL server listens on 0.0.0.0:2001
9. RCON listens on 0.0.0.0:19999
10. `[LLMBridge] Bridge healthy, LLM mode active`
11. `[LLMBridge] SITREP sent` — periodic updates to Python bridge

## What does NOT work

| Approach | Result |
|----------|--------|
| `-config` + `-addons` + `-addonsDir` | ❌ "config cannot be used together with addons!" |
| `-world` + `-addons` + `-addonsDir` | ❌ Hangs on "Attempting online Game Config" |
| `-config` + `-addonsDir` (no `-addons`) | ❌ 5633 files, mod "Available" but not "Loaded" |
| Packed `.pak` in DS addons folder | ❌ "Available" but not "Loaded" (DS only loads core+data as base) |
| `game.mods[]` with GUID (before publishing) | ❌ "Addon was not found on workshop" |
| **`game.mods[]` with GUID (after publishing)** | **✅ WORKS!** |

## Publishing mod to BI Workshop

1. Open Arma Reforger Workbench (`ArmaReforgerWorkbenchSteamDiag.exe`)
2. Load the mod project (`addon.gproj`)
3. Set workshop metadata (name, description, tags, unlisted=true)
4. Package + Publish
5. Output in `%LOCALAPPDATA%\Temp\Arma Reforger Workbench\Publishing\<GUID>\`:
   - `data.pak`, `resourceDatabase.rdb`, `addon.gproj`, `manifest.json`
6. Verify at `https://reforger.armaplatform.com/workshop/7E5A1C9B3D8F2406`

## DS port reference
- **RPL**: 2001 (game network)
- **RCON**: 19999 (admin, password: `llmadmin`)
- **A2S**: 17777 (Steam query)

## DS install location
`Q:\SteamLibrary\steamapps\common\Arma Reforger Server\`

## Key scenario IDs
| Scenario | scenarioId |
|----------|-----------|
| CTI Campaign Eden | `{ECC61978EDCC2B5A}Missions/23_Campaign.conf` |
| CombatOps Eden | `{58D0FB3206B6F859}Configs/Scenarios/CombatOps_Eden/Journal_CO_Eden.conf` |

## Connecting to the DS
From the game client: Multiplayer → Server Browser → Direct Connect → `127.0.0.1:2001`
