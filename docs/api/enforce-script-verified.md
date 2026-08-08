# Enforce Script Verified API Reference

> Complete verified API reference extracted from the Arma Reforger Doxygen documentation.
> All signatures below are confirmed against the official Script API docs (see source below).
>
> **WARNING**: Only use methods listed here. If a method is not documented here, verify it
> against the Doxygen docs before using. See [Engine Constraints](../reference/constraints.md)
> for the anti-hallucination list of things that do NOT exist.

---

## Source

- **Doxygen API docs**: `Q:\SteamLibrary\steamapps\common\Arma Reforger Tools\Workbench\docs\ArmaReforgerScriptAPIPublic.zip`
- **Size**: 98 MB, 29,234 entries
- **Tool**: Extract and search via Doxygen HTML output or `grep` on the extracted `.html` files

---

## SCR_AIGroup (Game script class for AI squad management)

The primary class for managing AI squad groups in Arma Reforger. Inherits from `AIGroup`.

```c
class SCR_AIGroup : AIGroup
```

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `SetGroupLeader` | `int playerID` | `void` | Sets the specified player as the group leader by player ID |
| `AddPlayer` | `int playerID` | `void` | Adds a player to the group by player ID |
| `SetNumberOfMembersToSpawn` | `int count` | `void` | Sets how many AI members to spawn when `SpawnUnits()` is called |
| `SpawnUnits` | — | `void` | Spawns the AI members configured via `SetNumberOfMembersToSpawn()` |
| `SetMaxMembers` | `int max` | `void` | Sets the maximum number of members (AI + players) the group can hold |
| `SetFaction` | `Faction faction` | `void` | Sets the faction of the group (e.g., US, USSR) |
| `SetRadioFrequency` | `int frequency` | `void` | Assigns a radio frequency/channel to the group |
| `AddWaypointToGroup` | `AIWaypoint waypoint` | `void` | Adds a waypoint for the group to navigate to |
| `RemoveWaypointFromGroup` | `AIWaypoint waypoint` | `void` | Removes a waypoint from the group's waypoint list |
| `GetAIMembers` | — | `array<SCR_ChimeraCharacter>` | Returns the AI members (not player-controlled) of the group |
| `GetWaypoints` | — | `array<AIWaypoint>` | Returns all waypoints currently assigned to the group |
| `IsPlayerLeader` | `int playerID` | `bool` | Returns true if the specified player is the group leader |
| `GetOnWaypointCompleted` | — | `ScriptInvoker` | Returns the waypoint completion event invoker (subscribe for callbacks) |
| `GetCenterOfMass` | — | `vector` | Returns the center position of all group members |
| `SetRequiredRank` | `SCR_ECharacterRank rank` | `void` | Sets the minimum rank required for members spawned in this group |

### Usage example (auto-squad creation)

```c
SCR_AIGroup group = SCR_AIGroup.Cast(
    GetGame().SpawnEntity(SCR_AIGroup, null, spawnCoords));

if (group) {
    group.SetNumberOfMembersToSpawn(5);
    group.SetMaxMembers(6);              // 5 AI + 1 player
    group.SetFaction(playerFaction);
    group.SetRadioFrequency(150);        // channel 150
    group.SetRequiredRank(SCR_ECharacterRank.PRIVATE);
    group.SpawnUnits();                 // spawns 5 AI
    group.AddPlayer(playerID);          // add the player
    group.SetGroupLeader(playerID);     // player becomes leader
}
```

---

## AIGroup (Base class)

The base class that `SCR_AIGroup` inherits from. Provides lower-level waypoint and agent management.

```c
class AIGroup : BaseContainerClass
```

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `AddWaypoint` | `AIWaypoint waypoint` | `void` | Adds a waypoint to the group (base method, SCR_AIGroup uses `AddWaypointToGroup`) |
| `RemoveWaypoint` | `AIWaypoint waypoint` | `void` | Removes a waypoint from the group |
| `GetCurrentWaypoint` | — | `AIWaypoint` | Returns the waypoint the group is currently moving toward |
| `GetAgents` | `out array<AIAgent> agents` | `void` | Fills the provided array with all agents (AI + player-controlled) in the group |
| `GetLeaderAgent` | — | `AIAgent` | Returns the agent that is currently the group leader |
| `SetNewLeader` | `AIAgent newLeader` | `void` | Sets a new group leader by agent reference |

### Notes

- Prefer `SCR_AIGroup.AddWaypointToGroup()` over `AIGroup.AddWaypoint()` — the SCR variant
  handles additional game logic (UI updates, radio, etc.).
- `GetLeaderAgent()` returns an `AIAgent`, not a player ID. To check if the leader is a
  player, compare its entity with the player's controlled entity.

---

## SCR_AIWorld (AI world management, script layer)

Manages all AI agents in the world. Can be modded to intercept agent addition/removal.

```c
class SCR_AIWorld : ChimeraAIWorld
```

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `AddedAIAgent` | `AIAgent agent` | `void` | Called when a new AI agent is added to the world. Override in `modded class` to track. |
| `RemovingAIAgent` | `AIAgent agent` | `void` | Called when an AI agent is being removed (killed/despawned). Override to track. |
| `GetAIAgents` (static) | `out array<AIAgent> agents` | `void` | Fills the array with all currently active AI agents in the world |

### Modding pattern (agent registry)

```c
modded class SCR_AIWorld
{
    static ref array<AIAgent> s_trackedAgents = {};

    override void AddedAIAgent(AIAgent agent)
    {
        super.AddedAIAgent(agent);
        s_trackedAgents.Insert(agent);
    }

    override void RemovingAIAgent(AIAgent agent)
    {
        super.RemovingAIAgent(agent);
        s_trackedAgents.RemoveItem(agent);
    }
}
```

This pattern is used by the AAC mod (see [AAC Mod Analysis](aac-mod-analysis.md)) and is the
basis for our `AAC_FactionAIRegistry` equivalent.

---

## AIWorld (Base class)

Base AI management. Controls global AI population limits.

```c
class AIWorld : GenericWorldEntity
```

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `SetAILimit` | `int limit` | `void` | Sets the global maximum number of concurrent AI agents |
| `GetAILimit` | — | `int` | Returns the current global AI limit |
| `GetCurrentNumOfActiveAIs` | — | `int` | Returns the current count of active AI agents |
| `GetLimitOfActiveAIs` | — | `int` | Returns the configured limit (same as `GetAILimit`) |

### Usage (prevent runaway spawning)

```c
AIWorld aiWorld = GetGame().GetWorld().GetAIWorld();
if (aiWorld) {
    int current = aiWorld.GetCurrentNumOfActiveAIs();
    int limit = aiWorld.GetAILimit();

    if (current >= limit) {
        Print("[LLMSquad] AI limit reached, cannot spawn more");
        return;
    }

    // Safe to spawn
}
```

---

## ChimeraAIWorld (Faction-level AI limits)

Provides per-faction AI limits. Inherits from `AIWorld`, parent of `SCR_AIWorld`.

```c
class ChimeraAIWorld : AIWorld
```

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `GetAILimitForFaction` | `FactionKey factionKey` | `int` | Returns the AI limit for a specific faction |
| `CanLimitedAIBeAddedForFaction` | `FactionKey factionKey` | `bool` | Returns true if more AI can be added for the given faction without exceeding the limit |

### Usage (faction-aware spawn check)

```c
ChimeraAIWorld aiWorld = ChimeraAIWorld.Cast(
    GetGame().GetWorld().GetAIWorld());

if (aiWorld) {
    FactionKey opforKey = "USSR";
    if (aiWorld.CanLimitedAIBeAddedForFaction(opforKey)) {
        // Safe to spawn OPFOR group
    } else {
        Print("[Stavka] OPFOR AI limit reached for faction");
    }
}
```

---

## SCR_PlayerController (Player spawn hook)

The controller class for each player. Can be modded to intercept player entity changes.

```c
class SCR_PlayerController : PlayerController
```

### Key method

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `OnControlledEntityChanged` | `IEntity from, IEntity to` | `void` | Called when the player's controlled entity changes. `to` is null on despawn, non-null on spawn. |

### Modding pattern (auto-squad trigger)

```c
modded class SCR_PlayerController
{
    override void OnControlledEntityChanged(IEntity from, IEntity to)
    {
        super.OnControlledEntityChanged(from, to);

        // Only run on the server
        if (!Replication.IsServer())
            return;

        // Only trigger when player gets a new entity (spawn)
        if (!to)
            return;

        int playerID = GetPlayerId();

        // Delay to allow entity initialization
        GetGame().GetCallqueue().CallLater(AutoSquadSpawn, 3000, false, playerID, to);
    }

    void AutoSquadSpawn(int playerID, IEntity playerEntity)
    {
        // ... auto-squad creation logic ...
    }
}
```

---

## SCR_PlayerControllerGroupComponent (Recruit AI)

Component on the player controller that handles group management operations.

```c
class SCR_PlayerControllerGroupComponent : ScriptComponent
```

### Method

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `RequestAddAIAgent` | `SCR_ChimeraCharacter character, int playerID` | `void` | Requests adding an AI character to the player's squad (server-side RPC) |

### Usage (recruit existing AI into squad)

```c
SCR_PlayerControllerGroupComponent groupComp = SCR_PlayerControllerGroupComponent
    .Cast(playerController.FindComponent(SCR_PlayerControllerGroupComponent));

if (groupComp && aiCharacter) {
    groupComp.RequestAddAIAgent(aiCharacter, playerID);
}
```

---

## AIWaypoint (Navigation point)

Defines a position the AI group should move to and how to behave there.

```c
class AIWaypoint : GenericEntity
```

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `SetCompletionRadius` | `float radius` | `void` | Sets the radius around the waypoint position that counts as "arrived" |
| `SetCompletionType` | `EAIWaypointCompletionType type` | `void` | Sets when the waypoint is considered complete (All, Leader, Any, etc.) |
| `SetPriorityLevel` | `float priority` | `void` | Sets the priority of this waypoint relative to others |
| `GetOrigin` | — | `vector` | Returns the position of the waypoint |

### EAIWaypointCompletionType enum

| Value | Description |
|---|---|
| `All` | All members must reach the completion radius |
| `Leader` | Only the leader must reach the radius |
| `Any` | Any single member reaching the radius completes it |

### Usage

```c
AIWaypoint wp = AIWaypoint.Cast(
    GetGame().SpawnEntity(AIWaypoint, null, coords));

if (wp) {
    wp.SetCompletionRadius(15.0);    // 15m radius
    wp.SetCompletionType(EAIWaypointCompletionType.All);
    wp.SetPriorityLevel(1.0);        // normal priority

    SCR_AIGroup group = ...;
    group.AddWaypointToGroup(wp);
}
```

---

## SCR_AIWaypoint (Script-layer waypoint)

Script-layer wrapper adding priority management.

```c
class SCR_AIWaypoint : AIWaypoint
```

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `GetCompletionRadius` | — | `float` | Returns the current completion radius |
| `GetPriorityLevel` | — | `float` | Returns the current priority level |
| `SetPriorityLevel` | `float priority` | `void` | Sets the priority level (overrides base) |

---

## REST API (Enforce Script HTTP client)

The REST system in Enforce Script is **callback-based and asynchronous**. There is no
synchronous HTTP call. All requests return immediately; responses arrive via `RestCallback`.

### Entry point

```c
RestApi restApi = GetGame().GetRestApi();
RestContext ctx = restApi.GetContext("http://127.0.0.1:5001");
```

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `GetGame().GetRestApi()` | — | `RestApi` | Returns the global REST API singleton |
| `RestApi.GetContext` | `string url` | `RestContext` | Creates a context bound to the given URL |
| `RestContext.GET` | `RestCallback cb, string path` | `void` | Issues an async GET request to `url + path` |
| `RestContext.POST` | `RestCallback cb, string path, string body` | `void` | Issues an async POST request with a JSON body string |

### RestCallback class

```c
class RestCallback
{
    void OnSuccess(string data, int dataSize);  // data = response body
    void OnError(int errorCode);                // errorCode = HTTP status
    void OnTimeout();                           // request timed out
}
```

### Complete usage pattern

```c
class LLMBridgeCallback : RestCallback
{
    string m_purpose;  // context tag

    void LLMBridgeCallback(string purpose)
    {
        m_purpose = purpose;
    }

    override void OnSuccess(string data, int dataSize)
    {
        PrintFormat("[LLMBridge] %1: received %2 bytes", m_purpose, dataSize);
        // Parse data as JSON, execute...
    }

    override void OnError(int errorCode)
    {
        PrintFormat("[LLMBridge] %1: error code=%2", m_purpose, errorCode);
        // Fallback: HOLD or maintain previous OPORD
    }

    override void OnTimeout()
    {
        PrintFormat("[LLMBridge] %1: timeout", m_purpose);
        // Fallback: HOLD or maintain previous OPORD
    }
}

// Usage:
RestContext ctx = GetGame().GetRestApi().GetContext("http://127.0.0.1:5001");
LLMBridgeCallback cb = new LLMBridgeCallback("SITREP");
ctx.POST(cb, "/sitrep", jsonBody);

LLMBridgeCallback cb2 = new LLMBridgeCallback("POLL_ORDERS");
ctx.GET(cb2, "/orders");
```

> **CRITICAL**: The following do NOT exist in Reforger Enforce Script:
> `new RestContext()`, `SetURL()`, `SetMethod()`, `SetBody()`, `Start()`, `ref RestContext`.
> They are Arma 3 / DayZ patterns. Using them compiles silently but does nothing.

---

## FileIO (Persistent storage)

File I/O for saving/loading configuration and state. Uses the `$profile:` prefix for
the profile directory.

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `FileIO.FileExists` | `string path` | `bool` | Checks if a file exists. Use `$profile:` prefix for profile-relative paths. |
| `FileIO.DeleteFile` | `string path` | `bool` | Deletes a file |

### Usage

```c
string configPath = "$profile:agent_squad_config.json";
if (FileIO.FileExists(configPath)) {
    // Load config
} else {
    // Use defaults and optionally save
}
```

---

## SCR_JsonLoadContext (JSON deserialization)

Loads JSON from a file and reads values by key.

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `LoadFromFile` | `string path` | `bool` | Loads a JSON file. Returns true on success. |
| `ReadValue` | `string key, out T val` | `bool` | Reads a value by key. `T` can be string, int, float, bool, vector. |

### Usage

```c
SCR_JsonLoadContext loader = new SCR_JsonLoadContext();
if (loader.LoadFromFile("$profile:agent_squad_config.json")) {
    int squadSize;
    string factionKey;
    int radioFreq;

    loader.ReadValue("squad_size", squadSize);
    loader.ReadValue("faction", factionKey);
    loader.ReadValue("radio_frequency", radioFreq);
}
```

---

## SCR_JsonSaveContext (JSON serialization)

Saves values to a JSON file by key.

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `WriteValue` | `string key, T val` | `void` | Writes a key-value pair. `T` can be string, int, float, bool, vector. |
| `SaveToFile` | `string path` | `bool` | Saves all written values to a JSON file. Returns true on success. |

### Usage

```c
SCR_JsonSaveContext saver = new SCR_JsonSaveContext();
saver.WriteValue("squad_size", 5);
saver.WriteValue("faction", "US");
saver.WriteValue("radio_frequency", 150);
saver.SaveToFile("$profile:agent_squad_config.json");
```

---

## Faction (Faction management)

Represents a faction (US, USSR, etc.) in the game.

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `GetFactionKey` | — | `FactionKey` (string) | Returns the faction key string (e.g., `"US"`, `"USSR"`) |
| `GetFactionColor` | — | `Color` | Returns the faction's UI color |

### Getting a faction reference

```c
SCR_FactionManager factionMgr = SCR_FactionManager.Cast(
    GetGame().GetFactionManager());

if (factionMgr) {
    Faction playerFaction = factionMgr.GetPlayerFaction(playerID);
    if (playerFaction) {
        FactionKey key = playerFaction.GetFactionKey(); // "US"
        Color color = playerFaction.GetFactionColor();
    }
}
```

---

## FactionAffiliationComponent (Entity faction lookup)

Component attached to entities that links them to a faction.

### Method

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `GetAffiliatedFaction` | — | `Faction` | Returns the faction this entity belongs to |

### Usage

```c
FactionAffiliationComponent factionComp = FactionAffiliationComponent
    .Cast(entity.FindComponent(FactionAffiliationComponent));

if (factionComp) {
    Faction faction = factionComp.GetAffiliatedFaction();
    if (faction) {
        FactionKey key = faction.GetFactionKey();
    }
}
```

---

## SCR_FactionManager (Faction manager)

Manages factions and player-faction assignments.

### Method

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `GetPlayerFaction` | `int playerID` | `Faction` | Returns the faction assigned to the given player |

---

## RplComponent (Network replication)

Component for network-replicated entities. Provides the replication ID.

### Method

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `Id` | — | `RplId` | Returns the network replication ID for this entity |

### Usage

```c
RplComponent rplComp = RplComponent
    .Cast(entity.FindComponent(RplComponent));

if (rplComp) {
    RplId entityId = rplComp.Id();
    // Use entityId for network identification
}
```

---

## Replication (Static replication utilities)

Static class for checking server/client context and triggering replication.

### Methods

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `Replication.IsServer()` | — | `bool` | Returns true if running on the server |
| `Replication.BumpMe()` | — | `void` | Triggers a replication update for the calling entity (dirty flag) |

### Usage

```c
// Only run spawn logic on the server
if (!Replication.IsServer())
    return;

// ... server-side spawn logic ...

// After changing replicated properties, mark dirty
Replication.BumpMe();
```

---

## Callqueue (Deferred execution)

The game's callqueue system for scheduling deferred or repeated method calls.

### Method

| Method | Parameters | Returns | Description |
|---|---|---|---|
| `GetGame().GetCallqueue().CallLater` | `method, delay_ms, repeat, args...` | `void` | Schedules a method call after `delay_ms`. If `repeat=true`, repeats at that interval. |

### Parameters

| Param | Type | Description |
|---|---|---|
| `method` | `function` | The method to call (e.g., `Update`, `AutoSquadSpawn`) |
| `delay_ms` | `int` | Delay in milliseconds before the call |
| `repeat` | `bool` | If true, repeats at this interval. If false, runs once. |
| `args...` | varies | Additional arguments passed to the method |

### Usage patterns

```c
// One-time delayed call (e.g., wait for entity init)
GetGame().GetCallqueue().CallLater(AutoSquadSpawn, 3000, false, playerID, entity);

// Repeating update loop (e.g., poll for orders every 2 seconds)
GetGame().GetCallqueue().CallLater(Update, 2000, true);

// In the modded game mode:
modded class SCR_BaseGameMode
{
    protected LLMBridge m_bridge;

    override void OnWorldPostProcess(World world)
    {
        super.OnWorldPostProcess(world);

        if (Replication.IsServer()) {
            m_bridge = new LLMBridge();
            // Poll bridge every 2 seconds
            GetGame().GetCallqueue().CallLater(Update, 2000, true);
        }
    }

    void Update()
    {
        if (m_bridge) {
            m_bridge.Update();  // poll /orders, send SITREPs
        }
    }
}
```

### Cancelling a repeating call

To cancel a repeating `CallLater`, use `GetGame().GetCallqueue().Remove(method)`:

```c
GetGame().GetCallqueue().Remove(Update);  // stop the repeating Update
```
