# Testing Workflow

> The empirical testing cycle for verifying changes to the Reforger LLM WarSim project.
> Every code change must be verified through this cycle — no exceptions.
> "It compiles" is not "it works." Only log evidence counts.

---

## Core Principle

> **Testing is empirical, always.** Kill → launch → wait → verify. No assumptions.
> A change that compiles may still crash the engine at runtime.

---

## Testing Cycle

### Step 1: Kill the running server/client

Kill any existing Arma Reforger processes to ensure a clean start:

```cmd
taskkill /F /IM ArmaReforgerSteam.exe
taskkill /F /IM ArmaReforgerServer.exe
```

### Step 2: Start the bridge (if testing REST integration)

```cmd
cd Q:\GAMES\Reforger-LLM-Squad
start_bridge.bat
```

Verify the bridge is listening:

```cmd
curl http://127.0.0.1:5001/status
```

Expected response: `{"status": "ok"}` or similar.

### Step 3: Launch the server

```cmd
start "Reforger Dedicated Server" /d "Q:\GAMES\Reforger-LLM-Squad\tools\ds1874900" ^
    ArmaReforgerServer.exe ^
    -config server.json ^
    -profile server_profile ^
    -backendlog ^
    -nothrow ^
    -log
```

### Step 4: Wait for server initialization

**Wait 20–30 seconds** for the server to fully initialize.

The server needs time to:
- Load the base game addons
- Load our mod addon
- Initialize the game world
- Start the RCON listener
- Register with the master server

### Step 5: Verify server startup via log

Check the latest server log for success indicators:

```cmd
powershell -NoProfile -File scripts\check_latest_log.ps1
```

**Success indicators** (look for these in the log):

| Indicator | Meaning |
|---|---|
| `Entered online game state` | Server successfully initialized the game world |
| `RCON Init` | RCON listener started successfully |
| `[LLMSquad]` | Our mod script is running (if component wiring is done) |
| No `SCRIPT (E)` errors in our script files | Our Enforce Script compiled without errors |

**Failure indicators:**

| Indicator | Meaning |
|---|---|
| Log file size ~1145 bytes | Crash — engine failed to initialize |
| `Unable to initialize the game` | Fatal initialization error |
| `Can't find '58D0FB3206B6F859'` | Base game addon not found (working directory issue) |
| `Can't find '7E5A1C9B3D8F2406'` | Our mod addon not found (addons path issue) |
| `Engine Initialization Error` | Cascade from one of the above |

### Step 6: Connect the client

```cmd
ArmaReforgerSteam.exe -connect 127.0.0.1:2001
```

> Using `-connect` bypasses the server browser, which:
> - Avoids downloading unwanted workshop subscriptions from other servers
> - Is faster for development iteration
> - Connects directly to the local server

### Step 7: Verify client-side behavior

After the client loads (10–20 seconds), verify in-game:

| Feature | How to verify |
|---|---|
| Mod loaded | Check client log for our mod GUID |
| Auto-squad (F1.2) | 5 AI squad members appear near player |
| Menu access | Game reaches main menu without crash |
| REST connectivity | `[LLMBridge]` lines in client log |

### Step 8: Check client log

```cmd
powershell -NoProfile -File scripts\check_latest_log.ps1
```

Or manually inspect the latest log:

```
C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<timestamp>\console.log
```

---

## Log Locations

| Log type | Path |
|---|---|
| Server log | `Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_<timestamp>\console.log` |
| Client log | `C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\logs\logs_<timestamp>\console.log` |
| Latest log detection | `scripts\check_latest_log.ps1` automatically finds the most recent log |

### Finding the latest log

```powershell
# Server logs:
Get-ChildItem "Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_*" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

# Client logs:
Get-ChildItem "$env:USERPROFILE\OneDrive\Documents\My Games\ArmaReforger\logs\logs_*" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
```

---

## Crash Diagnosis

### Crash signature

A crashed server produces a log file of approximately **1145 bytes** containing the
error message but no successful initialization lines.

```powershell
# Check log size — if ~1145 bytes, it's a crash:
$log = Get-ChildItem "Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_*" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host "Log size: $($log.Length) bytes"
if ($log.Length -lt 2000) {
    Write-Host "CRASH DETECTED — log is suspiciously small"
    Get-Content $log.FullName
}
```

### Common crash causes

| Error in log | Root cause | Fix |
|---|---|---|
| `Can't find '58D0FB3206B6F859'` | Working directory not the game dir | Fix `start /d` path |
| `Can't find '7E5A1C9B3D8F2406'` | Mod not in addons directory | Verify `.pak` file location |
| `SCRIPT (E) ... LLMBridge.c:42` | Our Enforce Script has an error | Fix line 42 in LLMBridge.c |
| `Unable to initialize the game` | Cascade from addon missing | Fix the root cause (above) |

### SCRIPT (E) cascade noise

> **IMPORTANT**: `SCRIPT (E)` errors in **base-game `.c` files** (in the `addons/` directory)
> that appear **AFTER** an error in **YOUR** script file are **cascade noise**.
>
> When your script has a compile error, the engine may produce secondary errors in base-game
> files that depend on your class. **Fix YOUR first error first.** The cascade errors
> will disappear once your script compiles cleanly.

#### How to identify your error vs. cascade noise

```
# Example console.log excerpt:
SCRIPT (E): Error on line 15: Cannot find symbol 'SetURL' in 'scripts/Game/LLMBridge.c'     ← YOUR error (fix this)
SCRIPT (E): Error on line 842: Something in 'addons/data/Scripts/Game/SCR_BaseGameMode.c'   ← CASCADE noise (ignore)
SCRIPT (E): Error on line 1203: Something in 'addons/data/Scripts/Game/SCR_PlayerController.c' ← CASCADE noise (ignore)
```

**Rule**: Find the FIRST `SCRIPT (E)` that references a file in YOUR mod directory
(`reforger_mod/addons/ReforgerLLMSquad/`). Fix that. Ignore subsequent errors in
`addons/` (base game) files.

---

## Test Scenarios

### Scenario 1: Mod compiles and game starts

| Step | Action | Expected result |
|---|---|---|
| 1 | Kill server | Processes terminated |
| 2 | Launch server | Server starts |
| 3 | Wait 20s | — |
| 4 | Run `check_latest_log.ps1` | Reports `OK` |
| 5 | Check log for `Entered online game state` | Present |
| 6 | Check log for no SCRIPT (E) in our files | Clean |

### Scenario 2: Auto-squad (F1.2) works

| Step | Action | Expected result |
|---|---|---|
| 1 | Complete Scenario 1 | Server running |
| 2 | Connect client with `-connect 127.0.0.1:2001` | Client loads |
| 3 | Wait 3 seconds after player spawns | — |
| 4 | Check log for `[LLMSquad] Auto-squad spawned` | Present |
| 5 | In-game: 5 AI squad members visible | Visual confirmation |
| 6 | Player is squad leader | Can issue orders |

### Scenario 3: Bridge communication (F1.3)

| Step | Action | Expected result |
|---|---|---|
| 1 | Start bridge (`start_bridge.bat`) | Bridge listening on 5001 |
| 2 | Start server with mod | Server initializes |
| 3 | Check bridge console | SITREP received from game |
| 4 | `curl http://127.0.0.1:5001/status` | Returns `{"status": "ok"}` |
| 5 | Check game log for `[LLMBridge]` lines | REST callbacks working |

### Scenario 4: LLM integration (Phase 2+)

| Step | Action | Expected result |
|---|---|---|
| 1 | Start bridge + verify LLM proxy | `curl http://192.168.1.35:11434/api/tags` returns models |
| 2 | Start server + connect client | Game running |
| 3 | Player sends tactical command | LLM responds within 5s |
| 4 | Check game log for waypoint execution | `[Tactical] waypoint assigned` |
| 5 | Squad moves to waypoint position | Visual confirmation |

---

## Quick Reference Commands

```cmd
:: Kill everything
taskkill /F /IM ArmaReforgerSteam.exe
taskkill /F /IM ArmaReforgerServer.exe

:: Start bridge
cd Q:\GAMES\Reforger-LLM-Squad && start_bridge.bat

:: Start server
start "Reforger Dedicated Server" /d "Q:\GAMES\Reforger-LLM-Squad\tools\ds1874900" ArmaReforgerServer.exe -config server.json -profile server_profile -backendlog -nothrow -log

:: Connect client (after server is up ~20s)
ArmaReforgerSteam.exe -connect 127.0.0.1:2001

:: Check latest log
powershell -NoProfile -File scripts\check_latest_log.ps1

:: Check LLM proxy
curl http://192.168.1.35:11434/api/tags

:: Check bridge health
curl http://127.0.0.1:5001/status

:: Find latest server log
dir /b /od "Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_*"

:: Grep for our mod output in log
findstr "LLMSquad" "Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_*\console.log"

:: Grep for errors in log
findstr "SCRIPT (E)" "Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_*\console.log"

:: Grep for guardrail rejections
findstr "[Guardrail]" "Q:\GAMES\Reforger-LLM-Squad\tools\server_profile\logs\logs_*\console.log"
```

---

## Iteration Speed

A typical development iteration takes:

| Step | Time |
|---|---|
| Kill processes | 2s |
| Start bridge (if needed) | 3s |
| Start server | 2s |
| Wait for server init | 20–30s |
| Verify log | 2s |
| Connect client | 10–15s |
| Verify in-game | 5–10s |
| **Total** | **~45–65s** |

> Plan for ~1 minute per iteration. Don't waste cycles — review your code carefully
> before each test launch.

---

## When Things Go Wrong

### Server won't start

1. Check working directory (`start /d` path)
2. Check `server.json` exists and is valid JSON
3. Check mod `.pak` is in the addons directory
4. Check `server_profile/` directory is writable

### Client can't connect

1. Verify server is running (`Entered online game state` in log)
2. Check port 2001 is open and not firewalled
3. Try `127.0.0.1:2001` (not `localhost:2001`)
4. Check mod checksums match between client and server

### Mod not loading

1. Verify GUID in `addon.gproj` is `7E5A1C9B3D8F2406`
2. Verify `.pak` file is in the correct `-addonsDir` path
3. Check for `Can't find '7E5A1C9B3D8F2406'` in the log
4. If using `game.mods[]`, verify the workshop ID is correct

### Bridge not receiving SITREP

1. Verify bridge is running (`curl http://127.0.0.1:5001/status`)
2. Check port matches (5001 in config.json, start_bridge.bat, LLMBridge.c)
3. Check for `[LLMBridge]` lines in the game log (mod is trying to send)
4. Check for `OnError` or `OnTimeout` in the game log (REST failing)
