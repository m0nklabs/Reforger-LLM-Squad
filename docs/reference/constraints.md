# Engine Constraints — Hard-Won Lessons

> A comprehensive list of things that do NOT exist, CANNOT be combined, or behave
> differently than expected in Arma Reforger / Enforce Script.
>
> Every item here was learned through a debug session. Read this before writing any
> Enforce Script or server configuration. Do NOT hallucinate features that don't exist.

---

## ⛔ Three Fatal Pitfalls

These three mistakes already cost a full debug session (2026-08-07). Do not repeat them.

### Pitfall 1: `-mod=` does NOT exist in Arma Reforger

| Wrong | Right |
|---|---|
| `-mod=@MyMod` | `-addonsDir <path> -addons <GUID>` |
| `-mod=C:\mods\MyMod` | (that's Arma 3 / DayZ syntax) |

The `-mod=` parameter is silently ignored by the Reforger engine. The engine gives
**no warning** that it was ignored. Your mod simply doesn't load, and you waste hours
wondering why your scripts aren't running.

**Correct mod loading:**

```cmd
ArmaReforgerSteam.exe ^
    -addonsDir "Q:\SteamLibrary\steamapps\common\Arma Reforger\addons" ^
    -addons 7E5A1C9B3D8F2406
```

### Pitfall 2: Working directory MUST be the game directory

If the working directory is not the game installation directory, the engine cannot
find `./addons` → `Can't find '58D0FB3206B6F859' game addon!` → Engine Initialization Error.

**This error means the BASE GAME is missing** — not your mod. The fix is to set the
working directory correctly using `start /d`:

```cmd
:: CORRECT — working directory is the game dir:
start /d "Q:\SteamLibrary\steamapps\common\Arma Reforger" ArmaReforgerSteam.exe ...

:: WRONG — working directory is whatever you're in now:
ArmaReforgerSteam.exe ...
```

### Pitfall 3: Never swap or reuse GUIDs

| GUID | What it is |
|---|---|
| `58D0FB3206B6F859` | The base game (`addons/data/ArmaReforger.gproj`) |
| `7E5A1C9B3D8F2406` | Our mod (`reforger_mod/addons/ReforgerLLMSquad/addon.gproj`) |

Never put `58D0FB3206B6F859` in our mod's `addon.gproj`, and never reference
`7E5A1C9B3D8F2406` as the base game. The pre-commit hook blocks GUID changes.

---

## CLI Parameter Constraints

### Parameters that do NOT exist

| Parameter | Status | Note |
|---|---|---|
| `-mod` | ❌ Does not exist | Arma 3 / DayZ only |
| `-mod=` | ❌ Does not exist | Arma 3 / DayZ only |
| `@modmap` | ❌ Does not exist | Arma 3 / DayZ only |

### Parameters that CANNOT be combined

| Combination | Result | Workaround |
|---|---|---|
| `-config server.json` + `-addons GUID` | ❌ Cannot be used together | Use `game.mods[]` in server.json for local mods |
| `-config` + `-addonsDir` | Depends on context | Test empirically |

> **Root cause**: `-addons` bypasses the server.json config path. If you need both
> server.json configuration AND local mods, list local mods in `game.mods[]` (which
> requires workshop publication) or restructure your addon loading approach.

### game.mods[] constraints

| Constraint | Impact |
|---|---|
| `game.mods[]` triggers workshop API lookup | Fails for local mods not published to workshop |
| `modId` is the workshop listing ID | NOT the addon GUID — these are different |
| Client downloads ALL workshop subscriptions on startup | Not just the server's mods — player's full subscription list |
| Client/server addon checksums must match | Connection rejected if mismatch |

---

## Enforce Script Constraints

### Language features that do NOT exist

| Feature | Status | Note |
|---|---|---|
| `modclass` keyword | ❌ Does not exist | Use `modded class` instead |
| Nested classes (class-in-class) | ❌ Not supported | Declare classes at file level |
| `ref RestContext` | ❌ Invalid type modifier | Use `RestContext` without `ref` |
| `World.GetGameTime()` | ❌ Does not exist | Use `GetGame().GetCallqueue()` for timing |

### REST API — patterns that do NOT work

These are Arma 3 / DayZ REST patterns. They compile silently but do nothing in Reforger:

| Pattern | Status | Correct approach |
|---|---|---|
| `new RestContext()` | ❌ Does not exist | `GetGame().GetRestApi().GetContext(url)` |
| `ctx.SetURL(url)` | ❌ Does not exist | URL is set at `GetContext()` time |
| `ctx.SetMethod(RestMethod.POST)` | ❌ Does not exist | Use `ctx.POST()` or `ctx.GET()` directly |
| `ctx.SetBody(jsonStr)` | ❌ Does not exist | Body is 3rd argument to `ctx.POST(cb, path, body)` |
| `ctx.Start()` | ❌ Does not exist | `POST()` and `GET()` return immediately (async) |

### Correct REST pattern (verified)

```c
// 1. Get context (URL bound at creation)
RestContext ctx = GetGame().GetRestApi().GetContext("http://127.0.0.1:5001");

// 2. Define callback
class MyCallback : RestCallback
{
    override void OnSuccess(string data, int dataSize) { /* handle */ }
    override void OnError(int errorCode) { /* handle */ }
    override void OnTimeout() { /* handle */ }
}

// 3. Issue request (async, non-blocking)
MyCallback cb = new MyCallback();
ctx.POST(cb, "/sitrep", jsonBodyString);
ctx.GET(cb, "/orders");
```

### Addon metadata format

| Wrong | Correct |
|---|---|
| `addon.json` | `addon.gproj` (GameProject format) |
| `gproj.conf` | `addon.gproj` |

---

## Server Configuration Constraints

### Fields that do NOT exist or behave unexpectedly

| Field | Status | Note |
|---|---|---|
| `gameProperties.disableBudget` | ❌ Not a valid field | TFU mod handles budgets via Game Mode attributes, not server config |
| `adminPassword` (top-level) | ⚠️ Legacy | Use `game.passwordAdmin` instead for in-game admin |
| `rcon.password` | ✅ Valid | But this is RCON password, NOT in-game admin password |

### In-game admin vs RCON password

| Concept | Field | How to use |
|---|---|---|
| In-game admin | `game.passwordAdmin` | Type `#login <password>` in in-game chat |
| RCON admin | `rcon.password` | Use RCON client (berconpy, etc.) |

> **Common mistake**: Setting `rcon.password` and expecting `#login` in chat to work.
> They are DIFFERENT passwords. `#login` uses `game.passwordAdmin`.

---

## RCON Constraints

### Minimal command set

Reforger RCON has a **minimal** command set. It does NOT support the extensive Arma 3
RCON commands:

| Available | NOT available |
|---|---|
| `#login` | Time/weather commands ❌ |
| `#kick` | Mission parameter changes ❌ |
| `#ban` | AI spawning ❌ |
| `#restart` | View distance changes ❌ |
| `#shutdown` | Loadout管理 ❌ |
| `#players` | Server config hot-reload ❌ |
| `#say` | — |
| `#announce` | — |

> If you need server-side control beyond these 8 commands, you must use Enforce Script
> (a mod loaded on the server), not RCON.

### TimeAndWeatherManagerEntity

Time and weather control requires **server-side Enforce Script**. The
`TimeAndWeatherManagerEntity` class exists but:
- It must be accessed from a mod loaded on the server
- It cannot be controlled via RCON
- The mod must be present in the server's addon directory

---

## GUID Reference

| GUID | What | File | Never change? |
|---|---|---|---|
| `58D0FB3206B6F859` | Base game (ArmaReforger) | `addons/data/ArmaReforger.gproj` | YES (engine) |
| `7E5A1C9B3D8F2406` | Our mod (ReforgerLLMSquad) | `reforger_mod/addons/ReforgerLLMSquad/addon.gproj` | YES (pre-commit hook) |
| `69A404653EE3F3C4` | AAC mod (reference) | External (workshop) | N/A (not our mod) |

---

## Client Connection Constraints

| Issue | Explanation | Fix |
|---|---|---|
| Server browser downloads ALL subscriptions | When a player opens the server browser, the client downloads ALL their workshop subscriptions, not just the current server's mods | Use `-connect 127.0.0.1:2001` to bypass the server browser entirely |
| Checksum mismatch on connect | Client and server must have identical mod versions | Ensure both have the same `.pak` file |
| `-connect` bypasses browser | Direct connection avoids unwanted downloads | Use `-connect <ip>:<port>` for development |

---

## Testing Constraints

### Crash signature

A crashed server/client produces a log file of approximately **1145 bytes** containing
`Unable to initialize the game` but no successful startup lines.

```powershell
# Quick check:
$log = Get-ChildItem "...\logs\logs_*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log.Length -lt 2000) { Write-Host "CRASH LIKELY" }
```

### SCRIPT (E) cascade noise

When your Enforce Script has a compile error, the engine produces:
1. **Your error** — `SCRIPT (E)` in your file (e.g., `scripts/Game/LLMBridge.c`)
2. **Cascade errors** — `SCRIPT (E)` in base-game files that depend on your class

**Fix YOUR first error first.** The cascade errors will disappear once your script
compiles cleanly. Do not waste time debugging base-game `.c` file errors — they are
noise.

### Log verification

The ONLY valid verification is `check_latest_log.ps1` reporting `OK`.
- "It compiles" is not "it works."
- "No crash dialog" is not "it works."
- Only log evidence with `OK` status counts.

---

## Security Constraints

| Rule | Enforcement |
|---|---|
| `config.json` contains API keys → NEVER commit | Gitignored + pre-commit hook blocks |
| Only commit `config.example.json` | Pre-commit hook checks |
| AGENTS.md is source of truth | CLAUDE.md and .goosehints are sync copies |
| After editing AGENTS.md, run `sync-agent-docs.bat` | Pre-commit hook checks for drift |
| Never change GUID in `addon.gproj` | Pre-commit hook blocks |
| Never `git add -f` on gitignored files | Manual discipline |

---

## Quick-Reference: What NOT to Do

| ❌ Don't | ✅ Do |
|---|---|
| `-mod=@MyMod` | `-addonsDir <path> -addons <GUID>` |
| Run without `start /d "<game_dir>"` | Always set working directory to game dir |
| `new RestContext()` | `GetGame().GetRestApi().GetContext(url)` |
| `ctx.SetMethod(RestMethod.POST)` | `ctx.POST(cb, path, body)` |
| `addon.json` | `addon.gproj` |
| `modclass` | `modded class` |
| Nested classes | File-level class declarations |
| `adminPassword` for in-game admin | `game.passwordAdmin` |
| Expect RCON to control time/weather | Use Enforce Script mod on server |
| Trust client log for server issues | Use server log at `server_profile/logs/` |
| Debug base-game SCRIPT (E) errors | Fix YOUR first error first |
| Commit `config.json` | Commit `config.example.json` only |
| Change GUID in `addon.gproj` | Never — pre-commit hook blocks it |
| Use `-config` + `-addons` together | Use `game.mods[]` in server.json |
| Claim "fixed" without log evidence | Run `check_latest_log.ps1` → must report `OK` |
