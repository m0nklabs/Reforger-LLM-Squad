# Safety and Guardrails

> Safety mechanisms and guardrails for the Reforger LLM WarSim system.
> These rules are enforced across all layers to prevent runaway behavior, cross-faction
> interference, and game crashes.

---

## 1. Namespace Isolation

The most critical guardrail: **BLUFOR and OPFOR AI brains never touch each other's groups.**

### Rule

| Brain | Can command | Cannot command |
|---|---|---|
| Tactical C2 (BLUFOR) | BLUFOR (US) squads only | OPFOR (USSR) groups — NEVER |
| Strategic Stavka (OPFOR) | OPFOR (USSR) groups only | BLUFOR (US) squads — NEVER |

### Enforcement layers

Namespace isolation is enforced at **three independent layers**. If any one layer fails,
the others catch the violation:

#### Layer 1: Pre-LLM (game mod, before sending request to bridge)

```c
// Tactical C2 — before sending player command to LLM:
Faction targetFaction = GetGroupFaction(targetGroup);
Faction playerFaction = SCR_FactionManager
    .Cast(GetGame().GetFactionManager())
    .GetPlayerFaction(playerID);

if (targetFaction.GetFactionKey() != playerFaction.GetFactionKey())
{
    Print("[Guardrail] Rejected: target group faction mismatch");
    return;  // Never send to LLM
}
```

#### Layer 2: Post-LLM (game mod, before executing returned command)

```c
// When executing command from GET /orders:
Faction groupFaction = GetGroupFaction(group);

// Tactical: only US
if (command.source == "TACTICAL" && groupFaction.GetFactionKey() != "US")
{
    Print("[Guardrail] Rejected: tactical command for non-BLUFOR group");
    return;
}

// Strategic: only USSR
if (command.source == "STAVKA" && groupFaction.GetFactionKey() != "USSR")
{
    Print("[Guardrail] Rejected: strategic command for non-OPFOR group");
    return;
}
```

#### Layer 3: Pydantic schema (bridge, before queueing command)

```python
class TacticalCommand(BaseModel):
    squad_id: str
    # Bridge validates squad_id is in BLUFOR registry
    faction: str  # Must be "US"

    @validator('faction')
    def validate_blufor(cls, v):
        if v != "US":
            raise ValueError("Tactical commands can only target BLUFOR")
        return v

class StrategicOrder(BaseModel):
    force_package: ForcePackage
    # ForcePackage.faction must be "USSR"

    @validator('force_package')
    def validate_opfor(cls, v):
        if v.faction != "USSR":
            raise ValueError("Strategic orders can only target OPFOR")
        return v
```

---

## 2. Priority Stack

When multiple orders conflict, the priority stack determines which executes:

| Priority | Source | Affects | Rule |
|---|---|---|---|
| 1 (highest) | STAVKA_OPORD | OPFOR only | Strategic orders override all lower-priority OPFOR behavior |
| 2 | CAPTAIN order | BLUFOR | Captain's tactical orders override Sergeant and below |
| 3 | SERGEANT order | BLUFOR | Sergeant's orders override AI autonomous behavior |
| 4 (lowest) | AI autonomous | Both | Default vanilla AI behavior (no LLM involvement) |

### Resolution logic

```c
bool ShouldOverride(SCR_AIGroup group, string newOrderSource,
                    string newOrderRank, string existingOrderSource)
{
    // Higher priority always overrides
    int newPriority = GetPriority(newOrderSource, newOrderRank);
    int existingPriority = GetPriority(existingOrderSource, "");

    if (newPriority > existingPriority)
        return true;

    // Same priority: newer replaces older (last-writer-wins)
    if (newPriority == existingPriority)
        return true;

    return false;
}

int GetPriority(string source, string rank)
{
    if (source == "STAVKA")   return 1;
    if (rank == "CAPTAIN")    return 2;
    if (rank == "SERGEANT")   return 3;
    return 4;  // AI autonomous
}
```

### Cross-namespace note

The priority stack is **within-namespace only**. A STAVKA_OPORD (priority 1) does NOT
override a CAPTAIN's BLUFOR order (priority 2), because they affect different factions.
The priority stack resolves conflicts between orders targeting the **same** group.

---

## 3. Passive Mode (Graceful Degradation)

If the bridge or LLM is unavailable, the game falls back to vanilla AI behavior.
**The game never crashes due to bridge/LLM failure.**

### Trigger conditions

| Condition | Detection | Response |
|---|---|---|
| Bridge process not running | REST `OnError` or `OnTimeout` | Enter passive mode (flag) |
| Bridge returns 500 | REST `OnError(errorCode=500)` | Enter passive mode (flag) |
| LLM call fails (bridge-side) | Bridge returns 503 | Game receives no new orders; vanilla AI continues |
| LLM returns invalid JSON | Parse failure in `OnSuccess` | Skip command, continue |
| Network partition | `OnTimeout` (repeated) | Enter passive mode after 3 consecutive timeouts |

### Passive mode behavior

```c
class LLMBridge
{
    protected bool m_passiveMode = false;
    protected int m_consecutiveFailures = 0;
    protected const int MAX_FAILURES = 3;

    void OnBridgeError()
    {
        m_consecutiveFailures++;
        if (m_consecutiveFailures >= MAX_FAILURES && !m_passiveMode)
        {
            m_passiveMode = true;
            Print("[LLMBridge] Entering passive mode — bridge unavailable, " +
                  "vanilla AI active");
        }
    }

    void OnBridgeSuccess()
    {
        if (m_passiveMode)
        {
            m_passiveMode = false;
            Print("[LLMBridge] Exiting passive mode — bridge restored");
        }
        m_consecutiveFailures = 0;
    }

    bool IsPassiveMode()
    {
        return m_passiveMode;
    }
}
```

### Passive mode impact

| System | In passive mode | When restored |
|---|---|---|
| Auto-squad | Already-spawned squads continue with vanilla AI | New players get auto-squad on next spawn |
| Tactical C2 | Player commands have no effect (HOLD) | Commands resume |
| Stavka | OPFOR groups maintain last waypoints | New cycle triggers on next timer tick |
| SITREP | Not sent (no bridge) | Reporting resumes |

---

## 4. Timeout Handling

Each brain has a specific timeout with a defined fallback:

### Tactical C2 timeout (3 seconds)

| Stage | Timeout | Fallback |
|---|---|---|
| REST POST to bridge | 3s | `OnError` → HOLD all squads |
| LLM inference | 3s (bridge-side) | Bridge returns 503 → game HOLDs |
| GET /orders poll | 2s | `OnTimeout` → skip cycle, retry next |

```c
// Tactical timeout fallback:
override void OnTimeout()
{
    Print("[Tactical] LLM timeout — issuing HOLD");
    HoldAllBLUFORSquads();  // clear waypoints, set HOLD at current position
}
```

### Strategic Stavka timeout (30 seconds)

| Stage | Timeout | Fallback |
|---|---|---|
| REST POST to bridge | 10s | `OnError` → maintain previous OPORD |
| LLM inference | 30s (bridge-side) | Bridge returns 503 → maintain previous OPORD |
| Entire cycle | 60s | Force-complete cycle, maintain previous OPORD |

```c
// Stavka timeout fallback:
override void OnTimeout()
{
    Print("[Stavka] LLM timeout — maintaining previous OPORD");
    // m_lastOpord is NOT cleared; existing groups keep their waypoints
    // Next cycle will retry
}
```

---

## 5. JSON Validation

All LLM output is validated before execution. **Hallucinated coordinates and invalid
actions are rejected.**

### Pydantic schemas (bridge-side)

```python
from pydantic import BaseModel, validator
from typing import List, Optional

class CommandParams(BaseModel):
    formation: Optional[str] = None
    stance: Optional[str] = None
    combat_mode: Optional[str] = None
    completion_radius: Optional[float] = 15.0
    replace_existing: Optional[bool] = True

    @validator('formation')
    def validate_formation(cls, v):
        if v is None: return v
        valid = {"WEDGE", "LINE", "COLUMN", "STAGGERED_COLUMN", "FILE", "DIAMOND"}
        if v not in valid:
            raise ValueError(f"Invalid formation: {v}")
        return v

    @validator('stance')
    def validate_stance(cls, v):
        if v is None: return v
        valid = {"STAND", "CROUCH", "PRONE"}
        if v not in valid:
            raise ValueError(f"Invalid stance: {v}")
        return v

    @validator('combat_mode')
    def validate_combat_mode(cls, v):
        if v is None: return v
        valid = {"HOLD_FIRE", "RETURN_FIRE", "OPEN_FIRE"}
        if v not in valid:
            raise ValueError(f"Invalid combat_mode: {v}")
        return v

class Command(BaseModel):
    command_id: str
    squad_id: str
    action: str
    position: Optional[List[float]] = None
    params: CommandParams = CommandParams()

    @validator('action')
    def validate_action(cls, v):
        valid = {"MOVE", "ATTACK", "DEFEND", "HOLD", "FORMATION", "STANCE"}
        if v not in valid:
            raise ValueError(f"Invalid action: {v}")
        return v

    @validator('position')
    def validate_position(cls, v, values):
        if v is None: return v
        # Arma Reforger Everon map bounds (approximate)
        # x: 0 to 12000, y: 0 to 500 (height), z: 0 to 12000
        if len(v) != 3:
            raise ValueError("Position must be [x, y, z]")
        if not (0 <= v[0] <= 12000):
            raise ValueError(f"Position x out of bounds: {v[0]}")
        if not (-100 <= v[1] <= 1000):
            raise ValueError(f"Position y out of bounds: {v[1]}")
        if not (0 <= v[2] <= 12000):
            raise ValueError(f"Position z out of bounds: {v[2]}")
        return v
```

### Position bounds (Everon map)

| Axis | Min | Max | Description |
|---|---|---|---|
| X | 0 | 12,000 | East-west (map width) |
| Y | -100 | 1,000 | Height (altitude) |
| Z | 0 | 12,000 | North-south (map depth) |

> These are approximate bounds for the Everon campaign map. If a different map is used,
> adjust the validators accordingly.

---

## 6. AI Limit Enforcement

`AIWorld.SetAILimit()` prevents runaway AI population growth. The Stavka brain checks
the limit before every spawn.

### Global AI limit

```c
AIWorld aiWorld = GetGame().GetWorld().GetAIWorld();
int current = aiWorld.GetCurrentNumOfActiveAIs();
int limit = aiWorld.GetAILimit();

// If spawning 8 OPFOR + 5 BLUFOR = 13 new AI
int needed = 13;
if (current + needed > limit)
{
    PrintFormat("[Guardrail] AI limit: current=%1, limit=%2, needed=%3 — " +
        "reducing spawn count", current, limit, needed);
    needed = limit - current;  // spawn only what fits
}
```

### Per-faction AI limit

```c
ChimeraAIWorld aiWorld = ChimeraAIWorld.Cast(
    GetGame().GetWorld().GetAIWorld());

if (!aiWorld.CanLimitedAIBeAddedForFaction("USSR"))
{
    Print("[Guardrail] OPFOR faction AI limit reached — cannot spawn");
    return;
}

int opforLimit = aiWorld.GetAILimitForFaction("USSR");
int opforCurrent = LLMSquadAIRegistry.GetFactionAgentCount("USSR");
PrintFormat("[Stavka] OPFOR AI: %1/%2", opforCurrent, opforLimit);
```

### Recommended limits

| Setting | Value | Rationale |
|---|---|---|
| Global AI limit | 80 | Balance between active battlefield and server performance |
| OPFOR faction limit | 40 | Leaves room for BLUFOR auto-squads (5 per player × ~8 players = 40) |
| BLUFOR faction limit | 40 | Auto-squad (5) + tactical reinforcements |

---

## 7. Faction Check Before Group Operations

Every group operation (spawn, waypoint, formation, stance) checks the faction
affiliation of the target group/entity before proceeding.

### Universal faction check function

```c
// Returns true if the group belongs to the expected faction
bool VerifyGroupFaction(SCR_AIGroup group, FactionKey expectedFaction)
{
    if (!group)
    {
        Print("[Guardrail] VerifyGroupFaction: group is null");
        return false;
    }

    // Get faction from first AI member (or player member)
    array<SCR_ChimeraCharacter> members = group.GetAIMembers();
    if (members.Count() == 0)
    {
        Print("[Guardrail] VerifyGroupFaction: group has no AI members");
        return false;
    }

    FactionAffiliationComponent comp = FactionAffiliationComponent
        .Cast(members[0].FindComponent(FactionAffiliationComponent));

    if (!comp)
    {
        Print("[Guardrail] VerifyGroupFaction: no FactionAffiliationComponent");
        return false;
    }

    Faction faction = comp.GetAffiliatedFaction();
    if (!faction)
    {
        Print("[Guardrail] VerifyGroupFaction: faction is null");
        return false;
    }

    FactionKey actualKey = faction.GetFactionKey();
    if (actualKey != expectedFaction)
    {
        PrintFormat("[Guardrail] Faction mismatch: expected=%1, actual=%2",
            expectedFaction, actualKey);
        return false;
    }

    return true;
}
```

### Usage in every critical path

```c
// Before spawning waypoint:
if (!VerifyGroupFaction(group, "US")) return;  // BLUFOR check
// ... add waypoint ...

// Before assigning tactical command:
if (!VerifyGroupFaction(group, "US")) return;  // BLUFOR check
// ... execute command ...

// Before spawning OPFOR group (Stavka):
if (!VerifyGroupFaction(group, "USSR")) return;  // OPFOR check
// ... add waypoint ...
```

---

## 8. Logging and Audit Trail

All guardrail-triggered rejections and fallback actions are logged for debugging:

### Log format

```
[Guardrail] <category> <message> [details]
```

### Categories

| Category | Example |
|---|---|
| `GUARD-NS` | `[Guardrail] GUARD-NS Rejected: tactical command for non-BLUFOR group [squad_id=OPFOR_SQUAD_3]` |
| `GUARD-PRIORITY` | `[Guardrail] GUARD-PRIORITY Order from CAPTAIN overrides SERGEANT [squad=BLUFOR_SQUAD_1]` |
| `GUARD-PASSIVE` | `[Guardrail] GUARD-PASSIVE Entering passive mode — bridge unavailable [consecutive_failures=3]` |
| `GUARD-TIMEOUT` | `[Guardrail] GUARD-TIMEOUT Tactical LLM timeout, issuing HOLD [squad=BLUFOR_SQUAD_1]` |
| `GUARD-JSON` | `[Guardrail] GUARD-JSON Invalid action value: FLANK [command_id=CMD-2026-0808-001]` |
| `GUARD-AILIMIT` | `[Guardrail] GUARD-AILIMIT AI limit reached: current=78, limit=80, needed=8` |
| `GUARD-FACTION` | `[Guardrail] GUARD-FACTION Faction mismatch: expected=USSR, actual=US` |

### Log analysis

All `[Guardrail]` lines are searchable in `console.log` for post-session analysis.
A script can grep for these to identify patterns (e.g., frequent LLM timeouts → consider
a faster model or lower temperature).

```powershell
# Find all guardrail rejections in the latest session:
Select-String -Path "$env:USERPROFILE\OneDrive\Documents\My Games\ArmaReforger\logs\logs_*\console.log" -Pattern "\[Guardrail\]" | Select-Object -Last 20
```

---

## Summary Table

| Guardrail | What it prevents | Where enforced |
|---|---|---|
| Namespace isolation | LLM commanding enemy faction | Pre-LLM (game), Post-LLM (game), Pydantic (bridge) |
| Priority stack | Low-rank overriding high-rank | Game mod (command execution) |
| Passive mode | Game crash on bridge/LLM failure | Game mod (REST callback) |
| Timeout handling | Hanging on unresponsive LLM | REST callback (OnTimeout) |
| JSON validation | Hallucinated coordinates/actions | Pydantic (bridge), game mod (parse) |
| AI limit | Server overload from too many AI | AIWorld/ChimeraAIWorld (game) |
| Faction check | Operations on wrong-faction groups | Game mod (every group op) |
| Audit logging | Silent failures | Game mod (Print with [Guardrail]) |
