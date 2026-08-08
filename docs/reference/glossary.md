# Glossary

> Terms and definitions used throughout the Reforger LLM WarSim project.
> Refer to this when encountering unfamiliar terminology.

---

## Military Terms

| Term | Definition |
|---|---|
| **BLUFOR** | Blue forces — the player's faction (typically US). Friendly forces. |
| **OPFOR** | Opposing forces — the enemy faction (typically Soviet/USSR). Hostile forces. |
| **Stavka** | Soviet high command — the strategic AI brain that orchestrates OPFOR forces at the theatre level. Named after the historical Soviet Armed Forces General Staff. |
| **SITREP** | Situation Report — a periodic snapshot of the world state (squad positions, enemy contacts, objectives, casualties) sent from the game to the bridge. |
| **OPORD** | Operations Order — a strategic command issued by the Stavka, containing objectives, force packages, timing, and fallback positions for OPFOR groups. |
| **C2** | Command and Control — the tactical brain that translates player orders into squad actions. |
| **PTT** | Push-to-talk — a future voice feature where players hold a key to transmit voice to the LLM. |
| **CAPTAIN** | A military rank (SCR_ECharacterRank.CAPTAIN) with tactical authority to issue orders and override lower ranks. |
| **SERGEANT** | A military rank (SCR_ECharacterRank.SERGEANT) with squad-level command authority. |

---

## Enforce Script Terms

| Term | Definition |
|---|---|
| **Enforce Script** | The scripting language used by Arma Reforger (`.c` files). Similar to C but with game-specific features. Not the same as Arma 3's SQF. |
| **SCR_AIGroup** | Reforger script class for AI squad management. Provides methods like `SpawnUnits()`, `AddWaypointToGroup()`, `SetGroupLeader()`. Inherits from `AIGroup`. |
| **AIGroup** | Base class for AI group management. Provides `AddWaypoint()`, `GetCurrentWaypoint()`, `GetAgents()`. Parent of `SCR_AIGroup`. |
| **AIWaypoint** | A navigation point assigned to an AI group. Defines a destination position, completion radius, completion type, and priority. |
| ** SCR_AIWaypoint** | Script-layer waypoint with priority management methods (`GetPriorityLevel()`, `SetPriorityLevel()`). Inherits from `AIWaypoint`. |
| **SCR_AIWorld** | Script-layer AI world manager. Can be modded to intercept agent addition (`AddedAIAgent`) and removal (`RemovingAIAgent`) for tracking. |
| **AIWorld** | Base AI management class. Controls global AI population limits via `SetAILimit()` and `GetAILimit()`. |
| **ChimeraAIWorld** | Faction-level AI limits. Provides `GetAILimitForFaction()` and `CanLimitedAIBeAddedForFaction()`. |
| **SCR_PlayerController** | The controller class for each player. Can be modded to hook `OnControlledEntityChanged()` for spawn detection. |
| **SCR_PlayerControllerGroupComponent** | Component on the player controller that handles group management. `RequestAddAIAgent()` recruits AI into the player's squad. |
| **Faction** | Represents a faction (US, USSR) in the game. Provides `GetFactionKey()` and `GetFactionColor()`. |
| **FactionAffiliationComponent** | Component on entities that links them to a faction. `GetAffiliatedFaction()` returns the faction. |
| **SCR_FactionManager** | Manages factions and player-faction assignments. `GetPlayerFaction(playerID)` returns a player's faction. |
| **SCR_ECharacterRank** | Enum of military ranks: PRIVATE, CORPORAL, SERGEANT, LIEUTENANT, CAPTAIN, MAJOR, COLONEL. |
| **EAIWaypointCompletionType** | Enum for waypoint completion: `All` (all members arrive), `Leader` (leader arrives), `Any` (any member arrives). |

---

## Networking Terms

| Term | Definition |
|---|---|
| **RplId** | Network replication identifier for entities. Each replicated entity has a unique `RplId` used for network synchronization. Obtained via `RplComponent.Id()`. |
| **RplComponent** | Component on network-replicated entities. Provides `Id()` to get the entity's RplId for network identification. |
| **RplRpc** | Remote procedure call over network replication. Used for client→server and server→client communication. Syntax: `[RplRpc(RplChannel.Reliable, RplRcver.Server)]`. |
| **RplProp** | Replicated property attribute (`[RplProp]`). Marks a field for automatic network synchronization — changes on the server propagate to all clients. |
| **Replication** | Static class for replication utilities. `Replication.IsServer()` checks if running on the server. `Replication.BumpMe()` triggers a replication update (dirty flag). |
| **RestContext** | HTTP REST client context in Enforce Script. Created via `GetGame().GetRestApi().GetContext(url)`. Supports `GET(cb, path)` and `POST(cb, path, body)`. Does NOT use `new RestContext()`. |
| **RestCallback** | Callback class for async REST responses. Override `OnSuccess(data, size)`, `OnError(code)`, `OnTimeout()`. |
| **RestApi** | The global REST API singleton. Accessed via `GetGame().GetRestApi()`. |

---

## Engine Concepts

| Term | Definition |
|---|---|
| **CallLater** | Deferred method execution via the game's callqueue. `GetGame().GetCallqueue().CallLater(method, delayMs, repeat, args...)`. Used for timers, delayed execution, and polling loops. |
| **Callqueue** | The game's job scheduler for deferred and repeating method calls. Accessed via `GetGame().GetCallqueue()`. |
| **addon.gproj** | GameProject metadata file for mod addons. NOT `addon.json` or `gproj.conf` (those don't exist). Contains the mod GUID and metadata. |
| **GUID** | Globally Unique Identifier for an addon. 16 hex characters (e.g., `7E5A1C9B3D8F2406`). The base game GUID is `58D0FB3206B6F859`; our mod GUID is `7E5A1C9B3D8F2406`. Never swap or reuse. |
| **$profile:** | Profile directory prefix for file paths in Enforce Script. `$profile:config.json` resolves to the profile directory (e.g., `C:\Users\...\My Games\ArmaReforger\config.json`). |
| **FileIO** | Enforce Script class for file I/O. `FileIO.FileExists(path)` checks file existence with `$profile:` prefix support. |
| **SCR_JsonLoadContext** | JSON deserialization context. `LoadFromFile(path)` + `ReadValue(key, out val)` to read JSON files from disk. |
| **SCR_JsonSaveContext** | JSON serialization context. `WriteValue(key, val)` + `SaveToFile(path)` to write JSON files to disk. |
| **modded class** | Enforce Script keyword for extending/modifying existing classes. `modded class SCR_PlayerController { ... }` adds to or overrides methods in the base class. Replaces Arma 3's `modclass` (which does NOT exist in Reforger). |

---

## Project Terms

| Term | Definition |
|---|---|
| **PakInspector** | CLI tool for extracting Reforger `.pak` files. Located at `tools/PakInspector.exe`, from [github.com/rvost/PakInspector](https://github.com/rvost/PakInspector). |
| **AAC** | Advanced AI Command — a community mod (GUID `69A404653EE3F3C4`, v1.0.2) whose source was extracted for reference patterns. See [AAC Mod Analysis](../api/aac-mod-analysis.md). |
| **F1.2** | Feature milestone — component wiring and auto-squad spawning. The next milestone to implement. See [Auto-Squad Spec](../design/auto-squad.md). |
| **Workbench** | The official Arma Reforger content creation tool. Located at `Q:\SteamLibrary\steamapps\common\Arma Reforger Tools\Workbench\`. Used for addon packaging, world editing, and resource management. |
| **Doxygen API docs** | The complete Enforce Script API documentation. 29,234 entries, 98 MB. Located at `...\Workbench\docs\ArmaReforgerScriptAPIPublic.zip`. The source for all verified method signatures. |

---

## Bridge / LLM Terms

| Term | Definition |
|---|---|
| **Bridge** | The Python FastAPI application that sits between the game and the LLM. Runs on `127.0.0.1:5001`. Receives SITREPs from the game, calls the LLM, returns commands. |
| **Ollama** | A local LLM inference server. Our proxy runs at `http://192.168.1.35:11434/v1` and is OpenAI-API-compatible. |
| **llama3** | The LLM model (8B parameters) used for both tactical and strategic AI. Provided by the Ollama proxy. |
| **Pydantic** | Python library for data validation using type hints. Used in the bridge to validate JSON payloads from both the game and the LLM. |
| **Passive mode** | A safety state where the game continues with vanilla AI because the bridge or LLM is unavailable. No crash — graceful degradation. |
| **Namespace isolation** | The guardrail ensuring BLUFOR commands never affect OPFOR groups and vice versa. Enforced at pre-LLM, post-LLM, and Pydantic layers. |
| **Priority stack** | The conflict resolution hierarchy: STAVKA_OPORD > CAPTAIN > SERGEANT > AI autonomous. Higher priority overrides lower when targeting the same group. |

---

## Server Terms

| Term | Definition |
|---|---|
| **server.json** | The dedicated server configuration file. Contains port, scenario, mods, RCON, and admin settings. |
| **server_profile** | The server's profile directory (logs, addons, saves). Located at `tools/server_profile/`. |
| **ds1874900** | The dedicated server installation directory. Located at `Q:\GAMES\Reforger-LLM-Squad\tools\ds1874900\`. |
| **RCON** | Remote console using the BattlEye protocol. Minimal command set: login, kick, ban, restart, shutdown, players, say, announce. Port 19999. |
| **berconpy** | Python library for BattlEye RCON communication. Async. Used in `scripts/rcon_test.py`. |
| **passwordAdmin** | The in-game admin password field in `game.passwordAdmin`. Used via `#login <password>` in chat. NOT `rcon.password`. |
| **game.mods[]** | The mod list in server.json. Triggers workshop API lookup. Cannot be used for local mods (use `-addons` instead, but `-addons` and `-config` can't combine). |

---

## Acronyms

| Acronym | Expansion |
|---|---|
| AAC | Advanced AI Command (community mod) |
| AI | Artificial Intelligence |
| API | Application Programming Interface |
| APL | Arma Public License |
| BLUFOR | Blue Forces (friendly) |
| C2 | Command and Control |
| CLI | Command Line Interface |
| F0, F1, F2... | Feature milestone numbers |
| GET/POST | HTTP request methods |
| GUI | Graphical User Interface |
| JSON | JavaScript Object Notation |
| LLM | Large Language Model |
| LOC | Lines of Code |
| MVP | Minimum Viable Product |
| OPFOR | Opposing Forces (enemy) |
| OPORD | Operations Order |
| PTT | Push-to-Talk |
| REST | Representational State Transfer |
| RCON | Remote Console |
| RPC | Remote Procedure Call |
| RPL | Replication (Enforce Script networking) |
| SCR | Script (Reforger script class prefix) |
| SITREP | Situation Report |
| TTS | Text-to-Speech |
| TFU | (mod) Tactical Framework Unit |
