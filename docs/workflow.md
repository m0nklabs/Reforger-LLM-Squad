# Development Workflow — Reforger LLM Squad

> Practical guide: how to develop, test, and deploy changes to the mod and bridge.

## Daily Workflow

### 1. Edit Mod Source
Edit `.c` files in: `reforger_mod/addons/ReforgerLLMSquad/Scripts/Game/`

### 2. Sync to 3 Locations
The DS compiles from the Workshop cache, NOT the local source. You must sync:
```powershell
$src = "Q:\GAMES\Reforger-LLM-Squad\reforger_mod\addons\ReforgerLLMSquad\Scripts\Game"
$ds = "Q:\SteamLibrary\steamapps\common\Arma Reforger Server\addons\ReforgerLLMSquad\Scripts\Game"
$ws = "C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\ReforgerLLMSquadControl_7E5A1C9B3D8F2406\Scripts\Game"

Copy-Item "$src\LLMBridge.c" "$ds\LLMBridge.c" -Force
Copy-Item "$src\LLMBridge.c" "$ws\LLMBridge.c" -Force
# Repeat for each changed file
```

### 3. Restart DS + Check Compile
```batch
taskkill /F /IM ArmaReforgerServer.exe
timeout /t 3
launch_ds.bat
REM Wait ~55s, then:
powershell -NoProfile -File scripts\check_latest_log.ps1
```
- **OK** = mod loaded, 0 compile errors in our files → ready to test
- **NO-GO** = compile errors → fix the FIRST error, rest is often cascade

### 4. Restart Bridge (if Python changed)
```batch
REM Kill old bridge processes
powershell -NoProfile -Command "Get-Process python -EA SilentlyContinue | Stop-Process -Force"
start_bridge.bat
REM Wait ~6s for startup
```

### 5. Connect & Test
- Launch Arma Reforger client
- Multiplayer → Direct Connect → `127.0.0.1:2001`
- Join a group (e.g., Atlas Red 1)
- Check bridge logs: `python_bridge/bridge.log`
- Run test suite: `cd python_bridge && python test_client.py`

## Key Paths

| What | Path |
|---|---|
| Mod source (EDIT HERE) | `Q:\GAMES\Reforger-LLM-Squad\reforger_mod\addons\ReforgerLLMSquad\` |
| DS local addons | `Q:\SteamLibrary\steamapps\common\Arma Reforger Server\addons\ReforgerLLMSquad\` |
| Workshop cache (OVERRIDES DS local!) | `C:\Users\onyou\...\ArmaReforger\addons\ReforgerLLMSquadControl_7E5A1C9B3D8F2406\` |
| Bridge source | `Q:\GAMES\Reforger-LLM-Squad\python_bridge\` |
| Bridge config | `python_bridge\config.json` (GITIGNORED) |
| Server config | `Q:\SteamLibrary\steamapps\common\Arma Reforger Server\server.json` |
| Game/DS logs | `C:\Users\onyou\...\ArmaReforger\logs\logs_<timestamp>\console.log` |
| Bridge logs | `Q:\GAMES\Reforger-LLM-Squad\python_bridge\bridge.log` |
| Doxygen API docs | `Q:\SteamLibrary\steamapps\common\Arma Reforger Tools\Workbench\docs\ArmaReforgerScriptAPIPublic.zip` |

## Breaking Changes & Lessons Learned

### Enforce Script Gotchas

1. **`ChimeraWorld` uses `CastFrom()`, NOT `Cast()`**
   - Wrong: `ChimeraWorld.Cast(GetGame().GetWorld())` → "Cast not supported"
   - Right: `ChimeraWorld.CastFrom(GetGame().GetWorld())`

2. **`str += int` fails — no auto-conversion in `+=`**
   - Wrong: `str += count;` → "Incompatible parameter"
   - Right: `str += "" + count;`
   - Also: `int.ToString()` does NOT exist. Use `"" + value`.

3. **`ref` arrays with engine classes**
   - Wrong: `ref array<ref SCR_AIGroup>` → "Strong ref not allowed"
   - Wrong: `array<SCR_AIGroup>` → "Variable is not strong ref"
   - Right: `ref array<SCR_AIGroup>` (ref on array, NOT on element)

4. **No static member variables on custom classes**
   - Wrong: `static StavkaController s_Instance;` → "Can't find variable"
   - Right: module-level global `StavkaController g_StavkaInstance;`

5. **REST callbacks get GC'd if not stored**
   - Wrong: `ctx.GET(new MyCallback(), "/health")` → callback never fires
   - Right: store in `ref array<ref MyCallback> m_aActiveCallbacks`

6. **POST body never transmits in Enforce**
   - `ctx.POST(cb, path, body)` sends request but body arrives empty
   - Right: use GET with query param `/sitrep?data=<urlencoded_json>`

7. **`QueryEntitiesBySphere` needs a callback function, NOT an array**
   - Wrong: `QueryEntitiesBySphere(pos, radius, array)` → "Can't make callback"
   - Right: `QueryEntitiesBySphere(pos, radius, QueryEntityCallback)` with module-level
     `bool QueryEntityCallback(IEntity ent) { ... return true; }`

8. **`EGetOutType` enum values are not publicly documented**
   - `EGetOutType.ALL`, `.GETOUT`, `.NORMAL` all fail
   - Workaround: use `AskOwnerToGetOutFromVehicle()` instead of `GetOutVehicle()`

9. **`Physics.Raycast()` not in public API**
   - Tried terrain analysis via raycast → "Undefined function"
   - Workaround: use squad Y position as elevation proxy

10. **Ternary `? :` doesn't work in string concatenation**
    - Wrong: `string s = cond ? "a" : "b"`
    - Right: `string s = "b"; if (cond) s = "a";`

### DS-Specific Lessons

11. **Workshop cache overrides DS local addons**
    - The DS downloads the mod from BI Workshop on first start
    - The cached version lives in `Documents\My Games\ArmaReforger\addons\`
    - This OVERRIDES the DS local addons directory
    - You MUST sync .c files to BOTH locations or the DS compiles old code

12. **Player joins group AFTER spawning**
    - AutoSquad fires 5s after entity change, but player hasn't joined a group yet
    - Fix: retry every 10s for up to 3 minutes (18 retries)
    - Also: LLMBridge.FindPlayerGroup() dynamically looks up the group each SITREP

13. **RPL authority required for entity spawning**
    - `SpawnEntityPrefab` on DS may fail with "Allowed server-side only!"
    - Always check `Replication.IsServer()` before spawning

14. **DS uses `game.mods[]` with addon GUID, not Steam ID**
    - `modId` = 16-char hex GUID from `addon.gproj` (NOT Steam publishedfileid)
    - Mod must be published to BI Workshop (even unlisted) first

15. **Master/Slave group architecture**
    - Player-facing UI = master group; AI agents = slave group
    - Always add AI via `slaveGroup.AddAgentFromControlledEntity(aiEnt)` (RPL broadcast)
    - `AddAgent()` has no RPL broadcast → clients never see the AI

## Commit Conventions

- Short, feature-scoped commit messages
- English everywhere (code, comments, docs, commits)
- Never commit `config.json` (pre-commit hook blocks this)
- Never change the GUID in `addon.gproj` (pre-commit hook blocks this)
- After editing AGENTS.md: run `scripts\sync-agent-docs.bat` before committing

## Test Cycle Checklist

- [ ] Edit `.c` files in `reforger_mod/addons/`
- [ ] Sync to DS local + Workshop cache (BOTH locations)
- [ ] Kill DS, restart via `launch_ds.bat`
- [ ] Wait 55s, run `check_latest_log.ps1` → must report OK
- [ ] If bridge changed: restart bridge, wait 6s
- [ ] Run `python test_client.py` → must be 9/9
- [ ] Connect game client, join group, verify AI spawns
- [ ] Check `bridge.log` for SITREP/LLM/Stavka activity
- [ ] Commit with descriptive message
