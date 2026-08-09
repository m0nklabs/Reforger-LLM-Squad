# Mod Setup — Arma Reforger (corrected 2026-08-07)

## What went wrong

The message `Can't find '58D0FB3206B6F859' game addon!` did NOT mean our mod was missing.
`58D0FB3206B6F859` is the GUID of the **base game itself**
(`<game>\addons\data\ArmaReforger.gproj`). The engine could not load its own game data
and then crashed with "Cannot initialize game project settings!" / "Engine Initialization Error".

Three root causes:

1. **`-mod=` does not exist in Arma Reforger** (that is Arma 3 / DayZ syntax). The engine
   silently ignores the parameter. Official wiki (Arma_Reforger:Startup_Parameters):
   - `-addonsDir <path>` — extra directory to search for mods
   - `-addons <GUID>` — comma-separated list of mod IDs (GUID from the .gproj file)
2. **Wrong working directory**: `start "" "<exe>"` inherited the batch file's CWD, so the
   relative addon dir `./addons` pointed at `Q:\GAMES\Reforger-LLM-Squad\addons` instead of
   the game folder. Fix: `start "" /d "<game_dir>" ...`
   (evidence: 7/7 bat launches failed this way; Steam launches worked fine)
3. **Wrong mod format**: `addon.json` / `gproj.conf` are invented formats — the engine does
   not read them. And the mod used the base-game GUID as its own ID (conflict).
   A real addon = folder with `addon.gproj` in GameProject format, with its OWN unique
   GUID and the base game as dependency.

## Correct structure

```text
reforger_mod/
  addons/
    ReforgerLLMSquad/          <- mod folder (name is free)
      addon.gproj              <- GameProject { ID, GUID, Dependencies }
      Scripts/Game/
        LLMBridge.c
```

Our mod GUID: `7E5A1C9B3D8F2406` (never use `58D0FB3206B6F859` — that is the base game).

## Correct launch (see launch_reforger.bat)

```bat
start "" /d "Q:\SteamLibrary\steamapps\common\Arma Reforger" "Q:\SteamLibrary\steamapps\common\Arma Reforger\ArmaReforgerSteam.exe" -addonsDir "Q:\GAMES\Reforger-LLM-Squad\reforger_mod\addons" -addons "7E5A1C9B3D8F2406"
```

## How to verify

Run: `powershell -NoProfile -File scripts\check_latest_log.ps1`
(newest log: `My Games\ArmaReforger\logs\logs_<timestamp>\console.log`)

- NO more `Game addon '58D0FB3206B6F859' not found`
- Log much larger than ~1145 bytes (= old crash signature)
- Lines containing `ReforgerLLMSquad` / loaded gproj
- Any `SCRIPT (E)` compile errors in LLMBridge.c = next step (F1.2)

## Status 2026-08-07 — FIXED & VERIFIED

The game now starts with the mod loaded and scripts compiled (console.log ~20KB+,
main menu reached). Script bugs fixed along the way:

| Error | Cause | Fix |
|---|---|---|
| `modclass LLMBridge : Component` | `modclass` does not exist in Enforce | `class LLMBridge` (wiring = F1.2) |
| line 46 "Broken expression" | nested classes (`class SquadMember` inside `class LLMBridge`) are not allowed | classes at file scope: `LLMSquadMember`, `LLMWaypoint` (also renamed to avoid clash with engine class `Waypoint`) |
| `new RestContext()` / `SetMethod` / `Start` | invented API | real API: `GetGame().GetRestApi().GetContext(url)` + `GET(cb, path)` / `POST(cb, path, body)` + `RestCallback` |
| "Method '~RestContext' is private" | `ref RestContext` = ownership, destructor is private | non-ref: `RestContext m_Rest;` |
| "Undefined function 'World.GetGameTime'" | does not exist in Reforger | own timer accumulated via `timeslice` in `Update()` |

Remaining warnings (deliberately kept, fully functional):
- `'OnSuccess'/'OnError' is obsolete: Use RestCallback.SetOnSuccess()` — deprecated
  override style, still works. Cleanup = later.

## Dedicated Server vs Listen Server (2026-08-09)

The **dedicated server** (`ArmaReforgerServer.exe`) **cannot load local unpublished mods**:

| Approach | Result |
|---|---|
| `-config` + `game.mods[]` with local GUID | `BACKEND (E): Addon was not found on workshop` → crash |
| `-config` + `-addons` CLI | `DEFAULT (F): -config cannot be used together with addons!` → crash |
| No `-config` + `-addons` CLI | Mod loads (5637 files) but server hangs at `BACKEND: Attempting online Game Config` |
| `-config` + `-addonsDir` (no `-addons`) | Server starts fine but mod NOT loaded (5633 = vanilla) |

**For development, use the listen server** (game exe + `-addonsDir` + `-addons` + host via in-game menu).
The listen server does NOT validate mods against the BI workshop backend.

**For production**, publish as unlisted workshop mod (Workbench GUI → Publish → visibility: unlisted).

## Play (offline) vs Host (multiplayer) — CRITICAL (2026-08-09)

This was the final blocker for F1.2. The game client has two ways to start a scenario:

| Action | Game instance | Mod loaded? | Scripts run? |
|---|---|---|---|
| **Play** (offline/single-player) | SAME instance (no destroy) | ✅ 5637 files | ✅ All modded classes execute |
| **Host** (multiplayer/listen server) | NEW instance (destroys first) | ❌ 5633 files (vanilla) | ❌ No modded classes |

**Always use Play (offline) for mod testing.** The `-addons` CLI parameter only applies to the first
game instance. When you click Host, the engine destroys the main-menu instance and creates a new
one with only the base game addons — your mod is "available" but not "loaded."

Log evidence:
```
# Play (offline) — WORKS:
12:48:08.046 DEFAULT: Entered offline game state.
12:48:08.184 [LLMGameMode] OnGameStart - Initializing LLM Bridge  ← MOD RUNS

# Host (multiplayer) — MOD LOST:
12:58:08.135 ENGINE: Game destroyed.
12:58:09.446 Module: Game; loaded 5633x files  ← VANILLA, NO MOD
```

## Packed vs Unpacked Mods (2026-08-09)

**Use unpacked mods for development.** Packed `.pak` files compile correctly but modded classes
do NOT execute at runtime — `Print()` output never appears in logs.

| Form | Compiles? | Modded classes run? | Use for |
|---|---|---|---|
| Unpacked (loose .c + addon.gproj) | ✅ 5637 files | ✅ Print() output appears | Development |
| Packed (.pak + addon.gproj + .rdb) | ✅ 5637 files | ❌ No Print() output | Workshop publishing only |

The `data.pak` must be generated via Workbench CLI for workshop publishing, but should NOT be
present in the development addons directory. If both `Scripts/` and `data.pak` exist, the engine
loads the packed version and modded classes silently fail.

## Cached Workshop Mods (2026-08-09)

If the user previously joined a community server, 100+ workshop mods may be cached in:
`C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\`

These cause `ADDON_LOAD_ERROR` and `error_failed_to_start_with_mods` when starting a scenario.
Fix: move all cached mod folders to an `addons_disabled/` subfolder:
```powershell
Move-Item 'C:\Users\onyou\OneDrive\Documents\My Games\ArmaReforger\addons\*' '...\addons_disabled\'
```
Our mod loaded via `-addonsDir` is separate and unaffected.

## Next step (F1.2 from PROJECT_PLAN)

`LLMBridge` is not instantiated anywhere yet -> NO `[LLMBridge]` lines appear in-game.
Wiring: `modded class SCR_BaseGameMode` that creates an `LLMBridge` on OnGameStart,
calls `Activate()`, and periodically calls `Update(timeslice)` via
`GetGame().GetCallqueue().CallLater()`.

## Recommended (wiki: Arma_Reforger:Mod_Project_Setup)

Install **Arma Reforger Tools** (free on Steam) for the Workbench: create projects,
live script compile errors, Play mode and Workshop publishing. The Tools ARE installed
on this machine (ArmaReforgerWorkbenchSteam.exe was seen running).

## Sources

- https://community.bistudio.com/wiki/Arma_Reforger:Startup_Parameters
- https://community.bistudio.com/wiki/Arma_Reforger:Mod_Project_Setup
- https://community.bistudio.com/wiki/Arma_Reforger:REST_API_Usage
- https://feedback.bistudio.com/T164922 (same "Check setup guidelines" message)
