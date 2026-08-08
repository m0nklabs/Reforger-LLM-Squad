# Tactical C2 — BLUFOR Command & Control Specification

> **Phase**: 2 (Tactical C2)
> **Faction**: BLUFOR (player's faction, typically US)
> **Latency target**: 2–5 seconds
> **Status**: 🔲 Planned (depends on F1.2 + F1.3)

---

## Overview

The Tactical C2 brain translates player commands into AI squad actions. A player sends
a natural-language order (via chat or an external REST tool), the bridge forwards it to
the LLM, and the LLM returns a structured JSON command that the game executes as a waypoint.

This is the "fast" brain — operating at squad level with 2–5 second latency for active
gameplay responsiveness.

---

## Architecture

```
Player text command
        │
        ▼
┌─── GAME MOD (Enforce Script) ───┐
│                                  │
│  LLMSquadController              │
│  ├── Capture player text        │
│  ├── Attach current SITREP      │
│  └── POST /api/c2/tactical      │
│        │                         │
└────────┼─────────────────────────┘
         │ (async REST via RestCallback)
         ▼
┌─── BRIDGE (FastAPI) ────────────┐
│                                  │
│  /api/c2/tactical                │
│  ├── Build LLM prompt            │
│  │   ├── System prompt (role)   │
│  │   ├── Context (SITREP)       │
│  │   └── User text              │
│  ├── Call LLM (llama3)          │
│  ├── Parse + validate JSON      │
│  └── Queue command              │
│                                  │
└────────┬─────────────────────────┘
         │
         ▼
┌─── LLM (Ollama llama3) ────────┐
│                                  │
│  Input: tactical prompt         │
│  Output: JSON command           │
│                                  │
└──────────────────────────────────┘
         │
         ▼ (polled by game via GET /orders)
┌─── GAME MOD ────────────────────┐
│                                  │
│  LLMBridge.Update()             │
│  ├── GET /orders                 │
│  ├── RestCallback.OnSuccess     │
│  ├── Parse command JSON          │
│  ├── Rank check                  │
│  ├── Faction check               │
│  └── SCR_AIGroup.AddWaypointToGroup()
│                                  │
└──────────────────────────────────┘
```

---

## Input Format

The game sends the player's text command plus the current tactical context (SITREP)
to the bridge:

```json
{
    "player_id": 42,
    "player_rank": "CAPTAIN",
    "text": "Squad, move to the hill at grid 047 126, keep low, wedge formation",
    "squad_id": "BLUFOR_SQUAD_1",
    "context": {
        "squad_position": [4800.0, 0.0, 6300.0],
        "squad_members": 5,
        "squad_status": "IDLE",
        "enemy_contacts": [
            {
                "position": [4600.0, 0.0, 5900.0],
                "strength": "unknown",
                "last_seen": "2026-08-08T21:25:00Z"
            }
        ],
        "current_objective": "SEIZE OBJ_ALPHA",
        "objectives": [
            {"id": "OBJ_ALPHA", "position": [4500.0, 0.0, 5000.0], "status": "IN_PROGRESS"}
        ]
    }
}
```

---

## LLM Model

| Property | Value |
|---|---|
| Model | `llama3` (8B parameters) |
| Provider | Ollama proxy at `http://192.168.1.35:11434/v1` |
| Temperature | 0.3 (low — deterministic tactical output) |
| Max tokens | 500 (commands are short) |
| Timeout | 3 seconds |

### System prompt (Tactical)

```
You are a tactical AI commander for a BLUFOR (US) squad in Arma Reforger.
Your role is to translate the player's natural-language order into a structured
JSON command.

Rules:
- Output ONLY valid JSON, no prose.
- Position coordinates are [x, y, z] in meters on the game map.
- If the player gives grid coordinates, convert to map position.
- If the player references a known objective, use its position from the context.
- Formation options: WEDGE, LINE, COLUMN, STAGGERED_COLUMN, FILE, DIAMOND
- Stance options: STAND, CROUCH, PRONE
- Combat mode options: HOLD_FIRE, RETURN_FIRE, OPEN_FIRE
- Action options: MOVE, ATTACK, DEFEND, HOLD, FORMATION, STANCE

Context (current SITREP):
{squad_position, enemy_contacts, objectives}

Respond with JSON in this format:
{
  "action": "<action>",
  "position": [x, y, z],
  "formation": "<formation>",
  "stance": "<stance>",
  "combat_mode": "<combat_mode>",
  "reasoning": "<brief tactical rationale>"
}
```

---

## Output Format

The LLM returns a JSON command:

```json
{
    "action": "MOVE",
    "position": [4700.0, 0.0, 6200.0],
    "formation": "WEDGE",
    "stance": "CROUCH",
    "combat_mode": "HOLD_FIRE",
    "reasoning": "Moving to elevated position at grid 047 126 to gain observation advantage while maintaining stealth with crouched wedge formation."
}
```

### Field validation

| Field | Required | Values |
|---|---|---|
| `action` | Yes | `MOVE`, `ATTACK`, `DEFEND`, `HOLD`, `FORMATION`, `STANCE` |
| `position` | For MOVE/ATTACK/DEFEND | `[x, y, z]` — must be within map bounds |
| `formation` | No | `WEDGE`, `LINE`, `COLUMN`, `STAGGERED_COLUMN`, `FILE`, `DIAMOND` |
| `stance` | No | `STAND`, `CROUCH`, `PRONE` |
| `combat_mode` | No | `HOLD_FIRE`, `RETURN_FIRE`, `OPEN_FIRE` |
| `reasoning` | No | Short string (for logging/debugging) |

---

## Latency Budget

| Stage | Budget | Notes |
|---|---|---|
| Game → Bridge (REST POST) | ~10ms | Localhost HTTP |
| Bridge → LLM prompt construction | ~5ms | String concatenation |
| LLM inference (llama3 8B) | 1.5–3.0s | Dominant cost; varies by prompt length |
| LLM → Bridge (JSON parse + validate) | ~5ms | Pydantic validation |
| Bridge → Game (poll lag) | 0–2s | Game polls every 2s; average 1s |
| Game waypoint execution | ~5ms | SCR_AIGroup.AddWaypointToGroup() |
| **Total** | **2–5s** | LLM inference + poll lag dominate |

> **Note**: The 335ms target mentioned in some early planning docs is unrealistic for
> an 8B LLM. 2–5 seconds is the honest budget. If lower latency is needed, consider a
> smaller model or pre-computed command templates.

---

## Rank Authority

The Tactical C2 system respects the military rank hierarchy. Only players with
sufficient rank can issue commands. The LLM does NOT enforce this — it is enforced
in the game mod before the command reaches the LLM.

### Rank hierarchy (SCR_ECharacterRank)

| Rank | Authority Level | Can command |
|---|---|---|
| PRIVATE | 0 | Cannot issue AI orders (can only request) |
| CORPORAL | 1 | Their own squad |
| SERGEANT | 2 | Their own squad + AI autonomous behavior override |
| LIEUTENANT | 3 | Multiple squads (platoon level) |
| CAPTAIN | 4 | Multiple squads + override SERGEANT orders |
| MAJOR | 5 | Company level |
| COLONEL | 6 | Battalion level |

### Enforcement logic (Enforce Script)

```c
bool CanPlayerCommand(int playerID, SCR_AIGroup targetGroup)
{
    // Get player's rank
    SCR_ECharacterRank playerRank = GetPlayerRank(playerID);

    // PRIVATES cannot issue orders
    if (playerRank < SCR_ECharacterRank.CORPORAL)
        return false;

    // Check if player is the leader of the target group
    if (targetGroup.IsPlayerLeader(playerID))
        return true;  // Squad leader can command their own squad

    // CAPTAIN+ can override orders for any BLUFOR group
    if (playerRank >= SCR_ECharacterRank.CAPTAIN)
        return true;

    // Otherwise, no authority
    return false;
}
```

### Priority stack

When multiple commanders issue conflicting orders, the priority stack resolves:

| Priority | Source | Rule |
|---|---|---|
| 1 (highest) | STAVKA_OPORD (OPFOR only) | Strategic orders; does NOT affect BLUFOR |
| 2 | CAPTAIN order | Overrides SERGEANT and below |
| 3 | SERGEANT order | Overrides AI autonomous behavior |
| 4 (lowest) | AI autonomous | Default vanilla AI behavior |

> See [Guardrails](guardrails.md) for the full priority stack with namespace isolation.

---

## Faction Isolation (Namespace)

The Tactical C2 brain operates exclusively in the **BLUFOR namespace**. It cannot
issue commands to OPFOR groups. This is enforced at multiple layers:

### Layer 1: Pre-LLM check (game mod)

```c
// Before sending to bridge:
Faction targetFaction = GetGroupFaction(targetGroup);
Faction playerFaction = SCR_FactionManager
    .Cast(GetGame().GetFactionManager())
    .GetPlayerFaction(playerID);

if (targetFaction.GetFactionKey() != playerFaction.GetFactionKey())
{
    Print("[Tactical] Rejected: target group is not BLUFOR");
    return;  // Don't even send to LLM
}
```

### Layer 2: Post-LLM check (game mod, on execution)

```c
// When executing the returned command:
Faction targetFaction = GetGroupFaction(targetGroup);
if (targetFaction.GetFactionKey() != "US")  // BLUFOR = US
{
    Print("[Tactical] Rejected: LLM returned command for non-BLUFOR group");
    return;  // Discard the command
}
```

### Layer 3: Pydantic schema (bridge)

```python
class TacticalCommand(BaseModel):
    squad_id: str
    # Bridge validates that squad_id is in the BLUFOR registry
    # before queueing the command
```

---

## Fallback Behavior

| Scenario | Fallback action | Rationale |
|---|---|---|
| Bridge unreachable (REST error) | HOLD all squads | Requests fail silently; vanilla AI takes over |
| LLM timeout (>3s) | HOLD position | Don't keep squads moving without fresh orders |
| LLM returns invalid JSON | HOLD position | Reject hallucinated output |
| LLM returns out-of-bounds position | HOLD position | Reject hallucinated coordinates |
| Player rank insufficient | Reject command, log | No authority — don't send to LLM at all |
| Target group is OPFOR | Reject command, log | Namespace violation |

### HOLD implementation

```c
void HoldGroup(SCR_AIGroup group)
{
    if (!group) return;

    // Clear existing waypoints and set a HOLD at current position
    vector currentPos = group.GetCenterOfMass();

    AIWaypoint holdWp = AIWaypoint.Cast(
        GetGame().SpawnEntity(AIWaypoint, null, currentPos));

    if (holdWp)
    {
        holdWp.SetCompletionRadius(5.0);
        holdWp.SetCompletionType(EAIWaypointCompletionType.All);
        holdWp.SetPriorityLevel(0.0);

        // Clear old waypoints, add hold
        array<AIWaypoint> existing = group.GetWaypoints();
        foreach (AIWaypoint wp : existing) {
            group.RemoveWaypointFromGroup(wp);
        }
        group.AddWaypointToGroup(holdWp);
    }

    PrintFormat("[Tactical] HOLD issued for squad at %1", currentPos.ToString());
}
```

---

## Execution Flow (Waypoint Assignment)

Once the game polls `GET /orders` and receives a validated tactical command:

```c
void ExecuteTacticalCommand(Command cmd)
{
    // 1. Find the target group
    SCR_AIGroup group = FindGroupById(cmd.squad_id);
    if (!group) return;

    // 2. Faction check (namespace isolation)
    Faction groupFaction = GetGroupFaction(group);
    if (groupFaction.GetFactionKey() != "US") return;

    // 3. Create waypoint
    AIWaypoint wp = AIWaypoint.Cast(
        GetGame().SpawnEntity(AIWaypoint, null, cmd.position));
    if (!wp) return;

    // 4. Configure waypoint based on action
    switch (cmd.action)
    {
        case "MOVE":
            wp.SetCompletionRadius(15.0);
            wp.SetCompletionType(EAIWaypointCompletionType.All);
            break;

        case "ATTACK":
            wp.SetCompletionRadius(50.0);  // wider for combat
            wp.SetCompletionType(EAIWaypointCompletionType.Leader);
            break;

        case "DEFEND":
            wp.SetCompletionRadius(10.0);
            wp.SetCompletionType(EAIWaypointCompletionType.All);
            break;
    }
    wp.SetPriorityLevel(1.0);

    // 5. Replace existing waypoints if specified
    if (cmd.params.replace_existing)
    {
        array<AIWaypoint> existing = group.GetWaypoints();
        foreach (AIWaypoint old : existing) {
            group.RemoveWaypointFromGroup(old);
        }
    }

    // 6. Assign waypoint
    group.AddWaypointToGroup(wp);

    // 7. Set formation, stance, combat mode (if specified)
    if (cmd.formation) SetFormation(group, cmd.formation);
    if (cmd.stance) SetStance(group, cmd.stance);
    if (cmd.combat_mode) SetCombatMode(group, cmd.combat_mode);

    // 8. Report result
    PostCommandResult(cmd.command_id, "SUCCESS");
}
```

---

## Future extensions (post-Phase 2)

- **Voice input**: PTT (push-to-talk) → speech-to-text → Tactical C2
- **Squad voice replies**: LLM generates squad ack ("Roger, moving to hill 047")
- **Multi-squad commands**: "All squads, converge on OBJ_ALPHA"
- **Battlefield analysis**: LLM analyzes SITREP and suggests orders proactively
