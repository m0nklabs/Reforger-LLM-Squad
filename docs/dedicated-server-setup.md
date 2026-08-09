# Dedicated Server Setup — Arma Reforger LLM Squad

## Status: PARTIALLY WORKING (2026-08-09)

- ✅ Vanilla DS starts and listens (RPL:2001, RCON:19999)
- ✅ Correct scenarioId found: `{ECC61978EDCC2B5A}Missions/23_Campaign.conf`
- ✅ Mod compiles on DS (5637 files with `-addons` flag)
- ❌ Local mod NOT loaded without `-addons` flag (5633 = vanilla)
- ❌ `-config` + `-addons` cannot be combined (hard DS check)
- ❌ `game.mods[]` triggers Steam Workshop validation
- ❌ `-world` without `-config` hangs on "Attempting online Game Config"

## Summary table

| Approach | Mod loads? | Server starts? | Notes |
|----------|-----------|---------------|-------|
| `-config` alone | ❌ 5633 files | ✅ Yes | Mod in addons folder, "Available" but not "Loaded" |
| `-config` + `-addons` + `-addonsDir` | ✅ 5637 files | ❌ No | "config cannot be used together with addons!" |
| `-world` + `-addons` + `-addonsDir` | ✅ 5637 files | ❌ No | Hangs on "Attempting online Game Config" |
| `-world` + `-addons` + `-addonsDir` + `-backendDisableStorage` | ✅ 5637 files | ❌ No | Still hangs on "Attempting online Game Config" |
| `-config` + `-addonsDir` (no `-addons`) | ❌ 5633 files | ✅ Yes | Same as `-config` alone |

## Root cause

The DS (build 190965, v1.7.0.54) has a **hard-coded check** that prevents
`-config` + `-addons` from being used together. The BI wiki claims they
can be combined, but this is outdated for the current version.

The DS loads addons differently from the game client:
- Game client: loads unpacked mods via `-addonsDir` + `-addons`
- DS: only loads addons with `.pak` files + `resourceDatabase.rdb` as base addons
- DS with `-addons` flag: compiles loose scripts (5637 files) but then rejects `-config`

## Two paths forward

### Path A — Pack the mod (recommended for local development)
1. Use Arma Reforger Workbench to pack the mod into a `.pak` file
2. Generate `resourceDatabase.rdb` for the mod
3. Place `.pak` + `.rdb` + `addon.gproj` in DS addons folder
4. DS will load it as a base addon (no `-addons` flag needed, no workshop validation)
5. Use `-config` alone — server starts with mod loaded

### Path B — Publish to Steam Workshop (for production/multiplayer)
1. Use Workbench to publish mod as unlisted workshop item
2. Add workshop ID to `game.mods[]` in `server.json`
3. Use `-config` alone — DS downloads mod from workshop and starts

## Files

- `launch_ds.bat` — DS launcher (syncs mod + starts server)
- `server.example.json` — Server config template (copy to DS dir)
- DS install: `Q:\SteamLibrary\steamapps\common\Arma Reforger Server\`

## DS vs Game Client comparison

| Feature | Game Client | Dedicated Server |
|---------|------------|-----------------|
| Mod loading | `-addonsDir` + `-addons` | `.pak` + `resourceDatabase.rdb` OR `game.mods[]` (workshop) |
| Scenario | In-game menu selection | `scenarioId` in config |
| `-config` | N/A | Required for network/RCON settings |
| `-addons` | Works with `-addonsDir` | Cannot be combined with `-config` |
| Unpacked mods | ✅ Supported | ❌ Not loaded (only "Available", not "Loaded") |
| `-autoStartScenario` | ❌ DS only | ✅ Works |
| `game.mods[]` | N/A | Triggers workshop validation |
| Backend | Optional | Required (or `-backendDisableStorage`) |

## Key scenario IDs

| Scenario | scenarioId |
|----------|-----------|
| CTI Campaign Eden | `{ECC61978EDCC2B5A}Missions/23_Campaign.conf` |
| CombatOps Eden | `{58D0FB3206B6F859}Configs/Scenarios/CombatOps_Eden/Journal_CO_Eden.conf` |

## DS port reference
- **RPL**: 2001 (game network)
- **RCON**: 19999 (admin)
- **A2S**: 17777 (Steam query)
