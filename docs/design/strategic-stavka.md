# Strategic Stavka — OPFOR Strategic AI Specification

> **Phase**: 3 (Strategic AI)
> **Faction**: OPFOR (enemy faction, typically Soviet)
> **Cadence**: 60–120 seconds
> **Status**: 🔲 Planned (depends on Phase 2)

---

## Overview

The Strategic Stavka brain is the "slow" brain that orchestrates OPFOR (enemy) forces
at the theatre level. Unlike the Tactical C2 brain (responds to player input in 2–5s),
the Stavka operates on a timer: it reads the full WorldState every 60–120 seconds,
makes strategic decisions via the LLM, and issues Operations Orders (OPORDs) that spawn
OPFOR groups and assign them objectives.

The name "Stavka" refers to the Soviet high command — the strategic brain that decides
where to attack, where to defend, and how to allocate forces across the theatre.

---

## Architecture

```
┌─── GAME MOD (Enforce Script) ───────────────────────┐
│                                                       │
│  StavkaController                                     │
│  ├── Timer: CallLater(StavkaCycle, 60000, true)      │
│  │                                                    │
│  ├── 1. Collect Full WorldState                      │
│  │   ├── All AI agents (BLUFOR + OPFOR)              │
│  │   ├── All squad_states                            │
│  │   ├── All objectives                              │
│  │   ├── Casualty counts                             │
│  │   └── AI population vs limit                      │
│  │                                                    │
│  ├── 2. POST /api/stavka/strategic                   │
│  │   Body: { world_state, faction: "USSR" }          │
│  │                                                    │
│  └── 3. RestCallback.OnSuccess(data):                │
│      ├── Parse OPORD JSON                             │
│      ├── For each order in OPORD.orders:              │
│      │   ├── Validate OPFOR faction                   │
│      │   ├── Check AI limit                           │
│      │   ├── SCR_AIGroup.SpawnUnits()                 │
│      │   ├── AIWaypoint → AddWaypointToGroup()        │
│      │   └── SetRadioFrequency()                      │
│      └── Log: "[Stavka] OPORD executed"               │
│                                                       │
└───────────────────────────────────────────────────────┘
         │
         ▼ (async REST POST)
┌─── BRIDGE (FastAPI) ─────────────────────────────────┐
│                                                       │
│  /api/stavka/strategic                               │
│  ├── Build strategic LLM prompt                      │
│  │   ├── System prompt (Stavka role)                 │
│  │   ├── Full WorldState JSON                        │
│  │   └── "Generate an OPORD" instruction             │
│  ├── Call LLM (llama3 or larger)                     │
│  ├── Parse + validate OPORD JSON (Pydantic)          │
│  └── Return OPORD to game                            │
│                                                       │
└───────────────────────────────────────────────────────┘
         │
         ▼
┌─── LLM (Ollama) ─────────────────────────────────────┐
│                                                       │
│  System: "You are the Stavka — Soviet High Command.  │
│  Read the full battlefield state and issue an OPORD   │
│  with objectives, force packages, and fallbacks."    │
│                                                       │
│  Input: Full WorldState JSON                          │
│  Output: OPORD JSON                                   │
│                                                       │
└───────────────────────────────────────────────────────┘
```

---

## Timer and Cadence

| Parameter | Value | Notes |
|---|---|---|
| Base interval | 60 seconds | `CallLater(StavkaCycle, 60000, true)` |
| Adaptive interval | 60–120 seconds | Slower during lulls, faster during active combat |
| Immediate trigger | On major event | If BLUFOR captures an objective, trigger immediately |
| Maximum delay | 120 seconds | Never wait more than 2 minutes between cycles |

### Timer implementation

```c
class StavkaController
{
    protected int m_cycleInterval = 60000;  // 60s base
    protected ref StrategicOpord m_lastOpord;  // for fallback

    void Start()
    {
        if (!Replication.IsServer()) return;

        Print("[Stavka] Controller started, 60s cycle");
        GetGame().GetCallqueue().CallLater(StavkaCycle, 60000, true);
    }

    void StavkaCycle()
    {
        if (!Replication.IsServer()) return;

        // 1. Collect full WorldState
        string worldStateJson = CollectWorldState();

        // 2. Send to bridge
        RestContext ctx = GetGame().GetRestApi()
            .GetContext("http://127.0.0.1:5001");
        StavkaCallback cb = new StavkaCallback(this);
        ctx.POST(cb, "/api/stavka/strategic", worldStateJson);

        // Callback handles the response asynchronously
    }
}
```

---

## Input: Full WorldState

The Stavka receives the complete battlefield picture — both BLUFOR and OPFOR forces,
all objectives, and casualty counts.

```json
{
    "world_state": {
        "timestamp": "2026-08-08T21:26:00Z",
        "phase": "ACTIVE_COMBAT",
        "squad_states": [
            {
                "squad_id": "BLUFOR_SQUAD_1",
                "faction": "US",
                "leader_rank": "CAPTAIN",
                "members": 4,
                "position": [4800.0, 0.0, 6300.0],
                "status": "MOVING",
                "current_waypoint": [5500.0, 0.0, 7000.0]
            },
            {
                "squad_id": "OPFOR_SQUAD_3",
                "faction": "USSR",
                "leader_rank": "SERGEANT",
                "members": 6,
                "position": [3500.0, 0.0, 4200.0],
                "status": "DEFENDING",
                "current_waypoint": [3500.0, 0.0, 4200.0]
            }
        ],
        "objectives": [
            {
                "id": "OBJ_ALPHA",
                "type": "SEIZE",
                "position": [4500.0, 0.0, 5000.0],
                "status": "CONTESTED",
                "controlling_faction": "CONTESTED"
            },
            {
                "id": "OBJ_BRAVO",
                "type": "DEFEND",
                "position": [3000.0, 0.0, 3500.0],
                "status": "HELD",
                "controlling_faction": "USSR"
            }
        ],
        "casualties": {
            "US": 3,
            "USSR": 8
        },
        "ai_population": {
            "US": 4,
            "USSR": 12,
            "total": 16,
            "limit": 80,
            "opfor_available_slots": 28
        }
    },
    "faction": "USSR"
}
```

---

## LLM Model

| Property | Value |
|---|---|
| Model | `llama3` (8B) — or larger if available on the proxy |
| Provider | Ollama proxy at `http://192.168.1.35:11434/v1` |
| Temperature | 0.5 (moderate — some variation for diverse strategies) |
| Max tokens | 2000 (OPORDs can be complex) |
| Timeout | 30 seconds (strategic decisions can take longer) |

> **Model verification**: Before production use, verify available models on the Ollama
> proxy with: `curl http://192.168.1.35:11434/api/tags`. Larger models (e.g., `llama3:70b`)
> may produce better strategic reasoning if available.

### System prompt (Strategic)

```
You are the Stavka — the Soviet High Command strategic AI for OPFOR (USSR) forces
in Arma Reforger. You receive a full battlefield state every 60-120 seconds and
must issue an Operations Order (OPORD) that directs OPFOR forces.

Your objectives:
- Contest or seize objectives currently held by BLUFOR (US).
- Defend objectives currently held by OPFOR (USSR).
- Allocate forces efficiently — don't over-commit to one objective.
- Account for casualties and available AI population limits.
- Provide fallback positions for every order.

Constraints:
- You can ONLY issue orders for OPFOR (USSR) groups. Never reference US forces
  as your own.
- Respect the AI population limit. Do not exceed available slots.
- Positions are [x, y, z] in meters on the game map.

Output ONLY valid JSON in this format:
{
  "opord_id": "STAVKA-<timestamp>",
  "orders": [
    {
      "objective": "SEIZE|DEFEND|REINFORCE|WITHDRAW",
      "location": [x, y, z],
      "force_package": {
        "group_type": "RIFLE_SQUAD|MACHINE_GUN_TEAM|RECON_TEAM|ARMORED_SECTION",
        "member_count": <int>,
        "faction": "USSR"
      },
      "timing": "IMMEDIATE|HOLD|DELAYED",
      "fallback": {
        "action": "WITHDRAW",
        "location": [x, y, z]
      }
    }
  ],
  "strategic_assessment": "<brief analysis of the battlefield situation>"
}
```

---

## Output: OPORD Format

The LLM returns an Operations Order — a structured set of strategic orders:

```json
{
    "opord_id": "STAVKA-2026-0808-211",
    "timestamp": "2026-08-08T21:26:00Z",
    "faction": "USSR",
    "strategic_assessment": "BLUFOR is advancing on OBJ_ALPHA with one squad. " +
        "OPFOR holds OBJ_BRAVO. Recommend reinforcing BRAVO and launching a " +
        "flanking attack toward ALPHA from the northeast.",
    "orders": [
        {
            "objective": "SEIZE",
            "location": [4500.0, 0.0, 5000.0],
            "force_package": {
                "group_type": "RIFLE_SQUAD",
                "member_count": 8,
                "faction": "USSR"
            },
            "timing": "IMMEDIATE",
            "fallback": {
                "action": "WITHDRAW",
                "location": [4200.0, 0.0, 4800.0]
            }
        },
        {
            "objective": "DEFEND",
            "location": [3000.0, 0.0, 3500.0],
            "force_package": {
                "group_type": "MACHINE_GUN_TEAM",
                "member_count": 4,
                "faction": "USSR"
            },
            "timing": "HOLD",
            "fallback": {
                "action": "WITHDRAW",
                "location": [2700.0, 0.0, 3200.0]
            }
        },
        {
            "objective": "REINFORCE",
            "location": [3000.0, 0.0, 3500.0],
            "force_package": {
                "group_type": "RECON_TEAM",
                "member_count": 3,
                "faction": "USSR"
            },
            "timing": "DELAYED",
            "fallback": {
                "action": "WITHDRAW",
                "location": [2500.0, 0.0, 3000.0]
            }
        }
    ]
}
```

### OPORD schema (Pydantic)

```python
class FallbackOrder(BaseModel):
    action: str  # WITHDRAW, DEFEND, HOLD
    location: List[float]

class ForcePackage(BaseModel):
    group_type: str  # RIFLE_SQUAD, MACHINE_GUN_TEAM, RECON_TEAM, ARMORED_SECTION
    member_count: int
    faction: str  # Must be "USSR"

class StrategicOrder(BaseModel):
    objective: str  # SEIZE, DEFEND, REINFORCE, WITHDRAW
    location: List[float]
    force_package: ForcePackage
    timing: str  # IMMEDIATE, HOLD, DELAYED
    fallback: FallbackOrder

class StrategicOpord(BaseModel):
    opord_id: str
    timestamp: str
    faction: str  # Must be "USSR"
    strategic_assessment: Optional[str] = None
    orders: List[StrategicOrder]
```

---

## Execution: Group Spawning + Waypoint Assignment

The game mod executes each order in the OPORD:

```c
void ExecuteOpord(StrategicOpord opord)
{
    int groupsSpawned = 0;
    int groupsFailed = 0;

    foreach (StrategicOrder order : opord.orders)
    {
        // ─── 1. Faction check (namespace isolation) ───
        if (order.force_package.faction != "USSR")
        {
            Print("[Stavka] Rejected: non-OPFOR faction in OPORD");
            groupsFailed++;
            continue;
        }

        // ─── 2. AI limit check ───
        ChimeraAIWorld aiWorld = ChimeraAIWorld.Cast(
            GetGame().GetWorld().GetAIWorld());

        if (aiWorld && !aiWorld.CanLimitedAIBeAddedForFaction("USSR"))
        {
            Print("[Stavka] OPFOR AI limit reached, skipping spawn");
            groupsFailed++;
            continue;
        }

        // ─── 3. Spawn position (offset from objective to avoid stacking) ───
        vector spawnPos = order.location + Vector(
            Math.RandomFloat(-50, 50), 0, Math.RandomFloat(-50, 50));

        // ─── 4. Create the OPFOR group ───
        SCR_AIGroup group = SCR_AIGroup.Cast(
            GetGame().SpawnEntity(SCR_AIGroup, null, spawnPos));

        if (!group)
        {
            Print("[Stavka] Failed to spawn group entity");
            groupsFailed++;
            continue;
        }

        // ─── 5. Configure the group ───
        group.SetNumberOfMembersToSpawn(order.force_package.member_count);
        group.SetMaxMembers(order.force_package.member_count);
        group.SetFaction(opforFaction);  // USSR Faction
        group.SetRadioFrequency(200 + groupsSpawned);  // assign unique freq
        group.SetRequiredRank(SCR_ECharacterRank.SERGEANT);

        // ─── 6. Spawn the AI units ───
        group.SpawnUnits();

        // ─── 7. Create and assign waypoint ───
        AIWaypoint wp = AIWaypoint.Cast(
            GetGame().SpawnEntity(AIWaypoint, null, order.location));

        if (wp)
        {
            // Radius depends on objective type
            float radius = 25.0;
            if (order.objective == "DEFEND") radius = 15.0;
            if (order.objective == "SEIZE") radius = 30.0;

            wp.SetCompletionRadius(radius);
            wp.SetCompletionType(EAIWaypointCompletionType.All);
            wp.SetPriorityLevel(1.0);

            group.AddWaypointToGroup(wp);
        }

        groupsSpawned++;
    }

    PrintFormat("[Stavka] OPORD %1 executed: %2 groups spawned, %3 failed",
        opord.opord_id, groupsSpawned, groupsFailed);
}
```

---

## Feedback Loop

The Stavka adapts based on battlefield events between cycles:

```
Cycle N: Stavka issues OPORD → groups spawned → combat ensues
    │
    ├── Kill events → WorldState updates immediately
    ├── Objective status changes → WorldState updates
    └── 60s later...
    │
Cycle N+1: Stavka reads updated WorldState
    │
    ├── Sees casualties → adjusts force packages
    ├── Sees objective captured → shifts focus
    └── Issues new OPORD → new groups spawned / existing redirected
```

### Kill event integration

```c
// Modded SCR_AIWorld — triggers immediate WorldState dirty flag
modded class SCR_AIWorld
{
    override void RemovingAIAgent(AIAgent agent)
    {
        super.RemovingAIAgent(agent);

        // Mark WorldState as dirty → next Stavka cycle uses fresh data
        LLMSquadAIRegistry.MarkDirty();

        // If this was a major loss, consider triggering early Stavka cycle
        Faction faction = LLMSquadAIRegistry.GetAgentFaction(agent);
        if (faction && faction.GetFactionKey() == "USSR")
        {
            int opforLosses = LLMSquadAIRegistry.GetFactionCasualtyCount("USSR");
            if (opforLosses % 5 == 0)  // every 5 OPFOR deaths
            {
                Print("[Stavka] Significant OPFOR losses — triggering early cycle");
                GetGame().GetCallqueue().CallLater(StavkaController.TriggerCycle, 5000, false);
            }
        }
    }
}
```

---

## Fallback Behavior

| Scenario | Fallback action | Rationale |
|---|---|---|
| Bridge unreachable | Maintain previous OPORD | Groups continue following last orders |
| LLM timeout (>30s) | Maintain previous OPORD | Strategic decisions can wait; don't leave groups idle |
| LLM returns invalid JSON | Maintain previous OPORD | Reject hallucinated output |
| LLM returns OPFOR faction violation | Maintain previous OPORD | Never let LLM command BLUFOR |
| AI limit reached | Spawn fewer/smaller groups | Respect engine limits |
| `SpawnUnits()` fails | Log error, continue with next order | Partial execution is acceptable |

### Maintaining previous OPORD

```c
class StavkaCallback : RestCallback
{
    protected StavkaController m_controller;

    override void OnTimeout()
    {
        Print("[Stavka] LLM timeout — maintaining previous OPORD");
        // m_lastOpord is NOT cleared — groups continue current waypoints
    }

    override void OnError(int errorCode)
    {
        PrintFormat("[Stavka] LLM error %1 — maintaining previous OPORD", errorCode);
        // Same: keep last OPORD active
    }

    override void OnSuccess(string data, int dataSize)
    {
        // Try to parse new OPORD
        StrategicOpord newOpord = ParseOpord(data);
        if (newOpord)
        {
            m_controller.m_lastOpord = newOpord;
            m_controller.ExecuteOpord(newOpord);
        }
        else
        {
            Print("[Stavka] Invalid OPORD JSON — maintaining previous");
            // Keep m_lastOpord unchanged
        }
    }
}
```

---

## Force Package Types

| Type | Members | Role | Notes |
|---|---|---|---|
| `RIFLE_SQUAD` | 6–8 | General purpose infantry | Standard OPFOR squad |
| `MACHINE_GUN_TEAM` | 3–4 | Suppression, defense | Good for DEFEND objectives |
| `RECON_TEAM` | 2–3 | Scouting, flanking | Fast, expendable |
| `ARMORED_SECTION` | 4–6 | Mechanized assault | Requires vehicle spawning (future) |

> **Note**: Vehicle spawning is not in Phase 3. ARMORED_SECTION will use dismounted
> infantry with appropriate loadout until vehicle spawning is implemented.

---

## Namespace Isolation

The Stavka operates exclusively in the **OPFOR namespace**:

1. **Input filter**: The bridge system prompt explicitly instructs the LLM to only
   issue orders for USSR forces.
2. **Output validation**: Pydantic schema requires `faction: "USSR"` in every force package.
3. **Execution check**: The game mod checks `order.force_package.faction != "USSR"` before
   spawning any group and rejects non-OPFOR orders.
4. **No BLUFOR access**: The Stavka controller never calls `SetFaction()` with a US faction.

> See [Guardrails](guardrails.md) for the complete namespace isolation specification.

---

## Future extensions (post-Phase 3)

- **Adaptive difficulty**: Stavka adjusts OPFOR strength based on BLUFOR performance
- **Persistent campaign state**: OPORD history influences future decisions
- **Multi-theatre coordination**: Multiple Stavka instances for different map sectors
- **Deception operations**: Stavka feints and misdirection to confuse BLUFOR
- **Logistics simulation**: Resupply, reinforcement timings, morale
