# AAC Mod Analysis — Advanced AI Command (Reverse Engineering)

> Analysis of the Advanced AI Command (AAC) community mod, extracted for reference patterns.
> The AAC mod demonstrates proven techniques for AI squad management in Arma Reforger that
> we can adapt for the Reforger LLM WarSim project.

---

## Mod Identity

| Field | Value |
|---|---|
| Mod name | Advanced AI Command |
| GUID | `69A404653EE3F3C4` |
| Version | 1.0.2 |
| Game version | 1.7.0.54 |
| License | APL (Arma Public License) |
| Source | Workshop (community mod) |

---

## Extraction Method

| Step | Detail |
|---|---|
| Tool | `tools/PakInspector.exe` (from [github.com/rvost/PakInspector](https://github.com/rvost/PakInspector)) |
| Input | `.pak` file from the AAC workshop addon |
| Output | `tools/aac_extracted/Scripts/Game/` |
| File count | 13 `.c` source files |
| Location | `Q:\GAMES\Reforger-LLM-Squad\tools\aac_extracted\Scripts\Game\` |

### Extraction command

```cmd
tools\PakInspector.exe extract --input "<addon_pak_path>" --output tools\aac_extracted\
```

---

## Extracted Source Files

| File | Size | Purpose |
|---|---|---|
| `AAC_PlayerControllerInit.c` | ~8 KB | Hooks player controller for group initialization and replication |
| `AAC_FactionAIRegistry.c` | ~6 KB | Static AI agent tracking via modded SCR_AIWorld |
| `AAC_RecruitGroupCommand.c` | ~5 KB | Recruit AI into player's squad |
| `AAC_OrderExecution.c` | ~91 KB | Full order execution engine (waypoints, formations, stances, garrison) |
| `AAC_FactionGroupResolver.c` | ~4 KB | Faction-based group filtering and resolution |
| `AAC_GroupClassifier.c` | ~3 KB | Group classification (friendly vs enemy) |
| `AAC_WaypointHelper.c` | ~4 KB | Waypoint creation utilities |
| `AAC_GroupUIHelper.c` | ~7 KB | Map UI for squad icons (NOT needed for our project) |
| `AAC_FormationHelper.c` | ~6 KB | Formation patterns (wedge, line, column) |
| `AAC_StanceHelper.c` | ~3 KB | Stance control (stand, crouch, prone) |
| `AAC_CombatModeHelper.c` | ~3 KB | Combat mode control (hold fire, return fire, open fire) |
| `AAC_GarrisonHelper.c` | ~8 KB | Building garrison (clearing buildings) |
| `AAC_VehicleHelper.c` | ~6 KB | Vehicle mounting/dismounting |

---

## Key Patterns We Can Reuse

### 1. Player Spawn Hook (AAC_PlayerControllerInit.c)

**Pattern**: Mod the `SCR_PlayerController` class, override `OnControlledEntityChanged()`,
and use `[RplProp]` arrays for group state replication.

```c
// AAC pattern (simplified from extracted source):
modded class SCR_PlayerController
{
    // Replicated properties — synced to all clients
    [RplProp(RplCopyMethod.Calculate)]
    protected ref array<int> m_aGroupMemberIds = {};

    [RplProp(RplCopyMethod.Calculate)]
    protected int m_iGroupLeaderId = -1;

    override void OnControlledEntityChanged(IEntity from, IEntity to)
    {
        super.OnControlledEntityChanged(from, to);

        if (!Replication.IsServer())
            return;

        if (to) {
            // Player spawned or respawned — initialize group
            // AAC uses RpcAsk for client→server order requests
        }
    }

    // Client → Server RPC for order requests
    [RplRpc(RplChannel.Reliable, RplRcver.Server)]
    void RpcAsk_IssueOrder(int groupRplId, vector destination, int orderType, bool replace)
    {
        // Server validates and executes the order
    }
}
```

**What we adapt**: The `OnControlledEntityChanged()` hook is our entry point for
[Auto-Squad (F1.2)](../design/auto-squad.md). We use the same pattern but trigger
auto-squad spawn instead of AAC's UI-driven approach.

**What we DON'T need**: The `[RplRpc]` client→server order system. Our orders come from
the LLM via REST, not from client input. However, if we later add in-game admin commands,
this pattern is proven.

---

### 2. AI Agent Registry (AAC_FactionAIRegistry.c)

**Pattern**: Mod `SCR_AIWorld` to intercept `AddedAIAgent()` and `RemovingAIAgent()`,
maintaining a static tracking array.

```c
// AAC pattern (simplified):
modded class SCR_AIWorld
{
    // Static registry — accessible from anywhere
    static ref array<AIAgent> s_aAllAgents = {};

    // Faction-indexed registry
    static ref map<FactionKey, ref array<AIAgent>> s_mFactionAgents = new map<FactionKey, ref array<AIAgent>>();

    override void AddedAIAgent(AIAgent agent)
    {
        super.AddedAIAgent(agent);
        s_aAllAgents.Insert(agent);

        // Index by faction
        Faction faction = GetAgentFaction(agent);
        if (faction) {
            FactionKey key = faction.GetFactionKey();
            if (!s_mFactionAgents.Contains(key))
                s_mFactionAgents.Set(key, {});
            s_mFactionAgents.Get(key).Insert(agent);
        }
    }

    override void RemovingAIAgent(AIAgent agent)
    {
        super.RemovingAIAgent(agent);
        s_aAllAgents.RemoveItem(agent);

        // Remove from faction index
        Faction faction = GetAgentFaction(agent);
        if (faction) {
            FactionKey key = faction.GetFactionKey();
            if (s_mFactionAgents.Contains(key))
                s_mFactionAgents.Get(key).RemoveItem(agent);
        }
    }

    // Helper to get all agents of a specific faction
    static array<AIAgent> GetAgentsByFaction(FactionKey factionKey)
    {
        if (s_mFactionAgents.Contains(factionKey))
            return s_mFactionAgents.Get(factionKey);
        return {};
    }

    // Helper — get the faction of an agent
    static Faction GetAgentFaction(AIAgent agent)
    {
        IEntity entity = agent.GetControlledEntity();
        if (!entity) return null;

        FactionAffiliationComponent comp = FactionAffiliationComponent
            .Cast(entity.FindComponent(FactionAffiliationComponent));
        if (!comp) return null;

        return comp.GetAffiliatedFaction();
    }
}
```

**What we adapt**: This exact pattern becomes our `LLMSquadAIRegistry` — the backbone of
the WorldState reporter. Every SITREP queries this registry to build the world snapshot
sent to the bridge.

---

### 3. Recruit Pattern (AAC_RecruitGroupCommand.c)

**Pattern**: Use `SCR_PlayerControllerGroupComponent.RequestAddAIAgent()` to move an
existing AI character into the player's squad.

```c
// AAC pattern:
void RecruitAI(SCR_ChimeraCharacter aiCharacter, int playerID)
{
    SCR_PlayerController controller = SCR_PlayerController
        .Cast(GetGame().GetPlayerManager().GetPlayerController(playerID));

    if (!controller) return;

    SCR_PlayerControllerGroupComponent groupComp = SCR_PlayerControllerGroupComponent
        .Cast(controller.FindComponent(SCR_PlayerControllerGroupComponent));

    if (!groupComp) return;

    // This sends a server-side RPC to add the AI to the player's group
    groupComp.RequestAddAIAgent(aiCharacter, playerID);
}
```

**What we adapt**: This is useful if we want to recruit already-spawned AI into a player's
squad (rather than spawning new ones). For F1.2 (auto-squad), we use `SpawnUnits()` instead,
but this pattern is documented for the recruit feature (potential F2.x).

---

### 4. Order Execution Engine (AAC_OrderExecution.c — 91 KB)

This is the largest file and the most directly applicable. It contains the full order
execution engine that translates high-level commands into `SCR_AIGroup` operations.

#### Key functions we can adapt:

| Function | Signature | Our Use |
|---|---|---|
| `IssueWaypoint` | `IssueWaypoint(SCR_AIGroup group, vector dest, EOrderType order, bool replace)` | Tactical C2 waypoint assignment |
| `ClearWaypoints` | `ClearWaypoints(SCR_AIGroup group)` | Cancel all current orders |
| `GetIn` | `GetIn(SCR_AIGroup group, IEntity vehicle)` | Mount into vehicle (future) |
| `GetOut` | `GetOut(SCR_AIGroup group)` | Dismount from vehicle (future) |
| `SetFormation` | `SetFormation(SCR_AIGroup group, EFormation formation)` | Formation control |
| `SetStance` | `SetStance(SCR_AIGroup group, EStance stance)` | Stance control |
| `SetCombatMode` | `SetCombatMode(SCR_AIGroup group, ECombatMode mode)` | Combat mode (fire discipline) |
| `Garrison` | `Garrison(SCR_AIGroup group, vector buildingPos, EGarrisonMode mode)` | Building garrison |
| `Attach` | `Attach(SCR_AIGroup follower, SCR_AIGroup leadGroup)` | Squad attachment (merging) |
| `Unmerge` | `Unmerge(SCR_AIGroup group)` | Split a squad from its parent |

#### IssueWaypoint pattern (adapted):

```c
// Simplified from AAC_OrderExecution.c:
void IssueWaypoint(SCR_AIGroup group, vector dest, int orderType, bool replace)
{
    if (!group) return;

    if (replace) {
        ClearWaypoints(group);
    }

    // Create waypoint at destination
    AIWaypoint wp = AIWaypoint.Cast(
        GetGame().SpawnEntity(AIWaypoint, null, dest));

    if (!wp) return;

    wp.SetCompletionRadius(15.0);
    wp.SetCompletionType(EAIWaypointCompletionType.All);
    wp.SetPriorityLevel(1.0);

    group.AddWaypointToGroup(wp);
}

void ClearWaypoints(SCR_AIGroup group)
{
    if (!group) return;

    array<AIWaypoint> waypoints = group.GetWaypoints();
    foreach (AIWaypoint wp : waypoints) {
        group.RemoveWaypointFromGroup(wp);
    }
}
```

---

### 5. Faction Group Resolver (AAC_FactionGroupResolver.c)

**Pattern**: Filter groups by faction to ensure commands only affect friendly units.

```c
// AAC pattern:
static array<SCR_AIGroup> GetGroupsForFaction(FactionKey factionKey)
{
    array<SCR_AIGroup> result = {};

    // Use the faction AI registry
    array<AIAgent> agents = AAC_FactionAIRegistry.GetAgentsByFaction(factionKey);

    foreach (AIAgent agent : agents) {
        AIGroup group = agent.GetParentGroup();
        if (group) {
            SCR_AIGroup scrGroup = SCR_AIGroup.Cast(group);
            if (scrGroup && result.Find(scrGroup) == -1) {
                result.Insert(scrGroup);
            }
        }
    }

    return result;
}
```

**What we adapt**: This is critical for our [namespace isolation guardrail](../design/guardrails.md).
BLUFOR commands must only affect BLUFOR groups; OPFOR commands must only affect OPFOR groups.

---

### 6. Group Classifier (AAC_GroupClassifier.c)

**Pattern**: Classify groups as friendly or enemy relative to a player.

```c
// AAC pattern:
enum EGroupClassification
{
    FRIENDLY,
    HOSTILE,
    NEUTRAL,
    UNKNOWN
}

static EGroupClassification ClassifyGroup(SCR_AIGroup group, int playerID)
{
    if (!group) return EGroupClassification.UNKNOWN;

    Faction playerFaction = SCR_FactionManager
        .Cast(GetGame().GetFactionManager())
        .GetPlayerFaction(playerID);

    if (!playerFaction) return EGroupClassification.UNKNOWN;

    FactionKey playerKey = playerFaction.GetFactionKey();

    // Check first member's faction
    array<SCR_ChimeraCharacter> members = group.GetAIMembers();
    if (members.Count() == 0) return EGroupClassification.UNKNOWN;

    FactionAffiliationComponent comp = FactionAffiliationComponent
        .Cast(members[0].FindComponent(FactionAffiliationComponent));

    if (!comp) return EGroupClassification.UNKNOWN;

    Faction groupFaction = comp.GetAffiliatedFaction();
    if (!groupFaction) return EGroupClassification.UNKNOWN;

    FactionKey groupKey = groupFaction.GetFactionKey();

    if (groupKey == playerKey) return EGroupClassification.FRIENDLY;

    // Check if factions are at war (simplified)
    return EGroupClassification.HOSTILE;
}
```

**What we adapt**: Used in the [Tactical C2](../design/tactical-c2.md) design to verify
that a BLUFOR player's command targets a BLUFOR group, and in the
[Guardrails](../design/guardrails.md) for namespace isolation enforcement.

---

## What AAC Does That We DON'T Need

| Feature | Why we don't need it |
|---|---|
| Map UI with squad icons | Our interface is LLM-driven, not UI-driven |
| Formation micro-management UI | The LLM decides formations, we just execute |
| Building clearing (Garrison with room-by-room) | Too granular for LLM control; basic garrison is sufficient |
| Client-side order preview/movement arrows | Orders come from LLM, not player mouse clicks |
| Drag-select multiple squads | We operate on one squad at a time per command |
| Vehicle waypoint visualization | Execution-only, no visualization needed |

---

## What AAC Does That We DO Need

| Feature | Source File | Our Equivalent |
|---|---|---|
| Player spawn hook | `AAC_PlayerControllerInit.c` | `LLMSquadController` (modded `SCR_PlayerController`) |
| AI agent registry | `AAC_FactionAIRegistry.c` | `LLMSquadAIRegistry` (modded `SCR_AIWorld`) |
| Recruit pattern | `AAC_RecruitGroupCommand.c` | Recruiting existing AI (future feature) |
| Waypoint execution | `AAC_OrderExecution.c` | `IssueWaypoint()` adapted for LLM JSON |
| Faction group filtering | `AAC_FactionGroupResolver.c` | `GetGroupsForFaction()` in our namespace isolation |
| Group classification | `AAC_GroupClassifier.c` | Faction check in command validation |
| Formation control | `AAC_FormationHelper.c` | `SetFormation()` from LLM JSON |
| Stance control | `AAC_StanceHelper.c` | `SetStance()` from LLM JSON |
| Combat mode control | `AAC_CombatModeHelper.c` | `SetCombatMode()` from LLM JSON |

---

## Adaptation Strategy

When implementing our project, we extract the *patterns* from AAC but write clean
implementations that integrate with our LLM bridge:

1. **Don't copy AAC code directly** — it's APL-licensed and designed for a different
   use case (player mouse-driven, not LLM-driven).
2. **Reuse verified method signatures** — AAC confirms that `SCR_PlayerControllerGroupComponent.RequestAddAIAgent()`,
   `SCR_AIGroup.AddWaypointToGroup()`, etc. work in practice.
3. **Reuse the modding patterns** — `modded class SCR_AIWorld` with `AddedAIAgent`/`RemovingAIAgent`
   overrides is proven to work.
4. **Skip UI code** — AAC's `AAC_GroupUIHelper.c` and formation visualization are not needed.
5. **Simplify order types** — AAC has dozens of order variants; we need ~6 (MOVE, ATTACK,
   DEFEND, HOLD, FORMATION, STANCE).

---

## License Compliance

- AAC is licensed under the **Arma Public License (APL)**.
- We do NOT copy AAC code into our project. We reference its patterns for educational purposes.
- Our Enforce Script is written from scratch, informed by AAC's demonstrated techniques.
- The extracted source in `tools/aac_extracted/` is for reference only and is NOT committed
  to our repository (gitignored).
