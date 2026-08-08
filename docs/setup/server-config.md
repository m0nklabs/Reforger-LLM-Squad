# Server Configuration Reference

> Dedicated server configuration for Arma Reforger running the ReforgerLLMSquad mod.
> Covers server.json structure, launch commands, RCON, admin access, and mod loading.

---

## server.json Structure

The dedicated server is configured via `server.json` (typically placed in the server
directory). This is the primary configuration file.

### Full structure with field explanations

```json
{
    "dedicatedServerId": "llmsquad-warsim",
    "region": "EU",
    "gameHostBindAddress": "0.0.0.0",
    "gameHostBindPort": 2001,
    "gameHostRegisterBindAddress": "127.0.0.1",
    "gameHostRegisterPort": 2001,
    "adminPassword": "",
    "game": {
        "name": "Reforger LLM WarSim",
        "password": "",
        "passwordAdmin": "llmsquad",
        "scenarioId": "{E5EFB36D8B89F8A2}Missions/23_Campaign.conf",
        "maxPlayers": 32,
        "visible": true,
        "crossPlatform": false,
        "moddingBlockHex": [],
        "gameProperties": {
            "serverMaxViewDistance": 1600,
            "serverMinGrassDistance": 50,
            "networkViewDistance": 1500,
            "disableThirdPerson": false,
            "fastValidation": true,
            "battlEyeAgent": true,
            "VONDisableUI": false,
            "VONDisableTransmit": false,
            "missionHeader": {
                "m_iPlayerCount": 32,
                "m_eEditableGameFlags": -1,
                "m_bRandomTimeOfDay": false,
                "m_sOSTMusic": "",
                "m_fMissionDuration": 0,
                "m_iStartHour": 12,
                "m_StartWeather": "SUNNY",
                "m_bWeatherLocked": false
            }
        },
        "mods": [
            {
                "modId": "5F0341B9B5A6F2C3",
                "name": "ReforgerLLMSquad",
                "version": "0.1.0"
            }
        ]
    },
    "rcon": {
        "address": "0.0.0.0",
        "port": 19999,
        "password": "rcon_password_here"
    }
}
```

### Field reference

| Field | Type | Description |
|---|---|---|
| `dedicatedServerId` | string | Unique identifier for the dedicated server instance |
| `region` | string | Server region for matchmaking (EU, NA, ASIA, etc.) |
| `gameHostBindAddress` | string | IP address the game server binds to (`0.0.0.0` = all interfaces) |
| `gameHostBindPort` | int | UDP port for game traffic (default 2001) |
| `gameHostRegisterBindAddress` | string | IP address registered to the master server for matchmaking |
| `gameHostRegisterPort` | int | Port registered to the master server |
| `adminPassword` | string | Legacy admin password (use `game.passwordAdmin` instead — see below) |
| `game.name` | string | Server name shown in server browser |
| `game.password` | string | Player join password (empty = open server) |
| `game.passwordAdmin` | string | **In-game admin password**. Use `#login <password>` in chat to become admin. |
| `game.scenarioId` | string | Scenario config file. `23_Campaign.conf` = Campaign Everon. |
| `game.maxPlayers` | int | Maximum player slots |
| `game.visible` | bool | Show server in public browser |
| `game.gameProperties.serverMaxViewDistance` | int | Max view distance for AI rendering |
| `game.gameProperties.serverMinGrassDistance` | int | Minimum grass rendering distance |
| `game.gameProperties.networkViewDistance` | int | View distance for network-relevant entities |
| `game.gameProperties.disableThirdPerson` | bool | Force first-person only |
| `game.gameProperties.fastValidation` | bool | Fast checksum validation (recommended true) |
| `game.gameProperties.battlEyeAgent` | bool | Enable BattlEye anti-cheat |
| `rcon.address` | string | RCON listen address |
| `rcon.port` | int | RCON port (default 19999) |
| `rcon.password` | string | RCON password (separate from in-game admin) |

### Current configuration

| Setting | Value | Source |
|---|---|---|
| Scenario | Campaign Everon | `{E5EFB36D8B89F8A2}Missions/23_Campaign.conf` |
| Port | 2001 | Game server port |
| RCON | Enabled on 19999 | BattlEye protocol |
| Admin password | `llmsquad` | `game.passwordAdmin` field (NOT `rcon.password`) |
| Dynamic AI Spawner | EE_Dynamic AI Spawner mod | Loaded via `game.mods[]` |
| Max players | 32 | `game.maxPlayers` |

---

## Launch Command

### Dedicated server

```cmd
start "Reforger Dedicated Server" /d "Q:\GAMES\Reforger-LLM-Squad\tools\ds1874900" ^
    ArmaReforgerServer.exe ^
    -config server.json ^
    -profile server_profile ^
    -backendlog ^
    -nothrow ^
    -log
```

### Parameter reference

| Parameter | Description |
|---|---|
| `-config server.json` | Path to the server configuration file |
| `-profile server_profile` | Profile directory for server data (logs, addons, saves) |
| `-backendlog` | Enable backend service logging |
| `-nothrow` | Disable exception throwing (prevents crash dialog on errors) |
| `-log` | Enable detailed logging to `console.log` |

### Critical: Working directory

> **The working directory MUST be the game directory** (`ds1874900/`).
> If the working directory is wrong, the engine cannot find `./addons` → `Can't find '58D0FB3206B6F859' game addon!`
> → Engine Initialization Error.
>
> The `start /d "..."` syntax in the launch command sets the working directory correctly.

### Client connection (bypassing server browser)

```cmd
ArmaReforgerSteam.exe -connect 127.0.0.1:2001
```

> Using `-connect` bypasses the server browser, which avoids downloading unwanted
> workshop subscriptions from other servers. This is the recommended way to connect
> to a local development server.

---

## RCON (Remote Console)

### Overview

Arma Reforger RCON uses the **BattlEye protocol** (same as Arma 3). It provides
minimal administrative commands.

### RCON configuration

```json
"rcon": {
    "address": "0.0.0.0",
    "port": 19999,
    "password": "rcon_password_here"
}
```

### RCON client (Python)

| Library | `berconpy` |
|---|---|
| File | `scripts/rcon_test.py` |
| Usage | Async Python RCON client for scripted server management |
| Protocol | BattlEye RCON over TCP |

### Available RCON commands

| Command | Description | Example |
|---|---|---|
| `#login <password>` | Authenticate as admin | `#login rcon_password_here` |
| `#kick <playerID> [reason]` | Kick a player | `#kick 42 teamkilling` |
| `#ban <playerID> [duration] [reason]` | Ban a player | `#ban 42 perm cheating` |
| `#restart` | Restart the mission | `#restart` |
| `#shutdown` | Shut down the server | `#shutdown` |
| `#players` | List online players | `#players` |
| `#say <message>` | Send a message to all players | `#say Server restarting in 5 min` |
| `#announce <message>` | Send a server announcement | `#announce Map change incoming` |

> **CRITICAL**: Reforger RCON has a **minimal command set**. There are NO time/weather
> commands, NO mission parameter changes, and NO AI spawning commands via RCON.
> Time and weather control requires server-side Enforce Script
> (via `TimeAndWeatherManagerEntity`), not RCON.

---

## In-Game Admin

### How it works

In-game admin uses the `game.passwordAdmin` field (NOT `rcon.password`).

| Concept | Field | How to use |
|---|---|---|
| In-game admin | `game.passwordAdmin` | Type `#login <password>` in in-game chat |
| RCON admin | `rcon.password` | Use RCON client with password |

### Becoming in-game admin

1. Join the server as a player
2. Open chat (default: `/` key or `J` for global chat)
3. Type: `#login llmsquad`
4. You now have admin privileges in-game

### In-game admin commands

Same basic commands as RCON: `#login`, `#kick`, `#ban`, `#restart`, `#shutdown`, `#players`,
`#say`, `#announce`.

> **Gotcha**: `rcon.password` and `game.passwordAdmin` are DIFFERENT passwords. If you
> set them to different values, RCON and in-game admin have separate credentials.

---

## Mod Loading

### Two methods

#### Method 1: Workshop mods (game.mods[])

```json
"mods": [
    {
        "modId": "5F0341B9B5A6F2C3",
        "name": "ReforgerLLMSquad",
        "version": "0.1.0"
    }
]
```

- Server downloads the mod from the workshop to `server_profile/addons/`
- `modId` is the **workshop listing ID** (NOT the addon GUID)
- Clients connecting to the server will auto-download the mod

> **Constraint**: `game.mods[]` triggers the workshop API lookup. This fails for local
> mods that are not published to the workshop. Local mods must be loaded via
> `-addonsDir` + `-addons` (see below).

#### Method 2: Local mods (-addonsDir + -addons)

```cmd
ArmaReforgerServer.exe ^
    -addonsDir "Q:\SteamLibrary\steamapps\common\Arma Reforger\addons" ^
    -addons 7E5A1C9B3D8F2406 ^
    -profile server_profile ^
    -log
```

- `-addonsDir` points to the directory containing addon `.pak` files
- `-addons` takes the addon **GUID** (e.g., `7E5A1C9B3D8F2406` for our mod)
- This bypasses the workshop entirely — the mod is loaded from the local filesystem

> **CRITICAL constraint**: `-config` and `-addons` **CANNOT be used together** on a
> dedicated server. If you need to load a local mod, you must use `game.mods[]` in
> the server.json config instead, or use `-addons` without `-config` (which limits
> server configuration options).
>
> See [Engine Constraints](../reference/constraints.md) for details.

### Mod GUIDs

| GUID | What it is | File |
|---|---|---|
| `58D0FB3206B6F859` | Base game (ArmaReforger) | `addons/data/ArmaReforger.gproj` |
| `7E5A1C9B3D8F2406` | Our mod (ReforgerLLMSquad) | `reforger_mod/addons/ReforgerLLMSquad/addon.gproj` |

> **NEVER swap or reuse these GUIDs.** The pre-commit hook blocks GUID changes.

### Client/server addon checksums

Client and server addon checksums must match. If they don't, the connection is rejected
with a mod mismatch error. Ensure:
1. Both server and client have the same mod version
2. The mod `.pak` file is identical (same checksum)
3. `fastValidation: true` in `gameProperties` catches mismatches early

---

## Server Profile Directory

| Path | Purpose |
|---|---|
| `tools/server_profile/` | Server profile root |
| `tools/server_profile/addons/` | Downloaded workshop mods |
| `tools/server_profile/logs/logs_<timestamp>/console.log` | Server logs |
| `tools/server_profile/config.json` | Runtime configuration (GITIGNORED) |

---

## Log Locations

| Log type | Path |
|---|---|
| Server log | `Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_<timestamp>\console.log` |
| Client log | `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<timestamp>\console.log` |
| Backend log | Included in server console.log when `-backendlog` is used |

---

## Common Server Issues

| Error | Cause | Fix |
|---|---|---|
| `Can't find '58D0FB3206B6F859' game addon!` | Working directory is not the game dir | Ensure `start /d "<game_dir>"` is correct |
| `Can't find '7E5A1C9B3D8F2406' addon!` | Our mod not found in addons dir | Verify mod `.pak` is in `-addonsDir` path |
| `Engine Initialization Error` | Base game addon missing (cascade from above) | Fix working directory or addons path |
| Connection rejected (mod mismatch) | Client/server mod versions differ | Ensure both have same mod version |
| RCON not responding | RCON not enabled or wrong port | Verify `rcon.port` and `rcon.password` in server.json |
| `disableBudget is not a valid field` | Using non-existent config field | Remove `gameProperties.disableBudget`; TFU mod handles budgets differently |
