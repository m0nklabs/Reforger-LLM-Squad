# Phased Implementation Roadmap

> Implementation roadmap for the Reforger LLM WarSim project — from MVP (Auto Squad)
> through Full WarSim (LLM vs LLM with voice and persistent campaign).
>
> Last updated: 2026-08-08

---

## Overview

The project follows a four-phase implementation plan. Each phase builds on the previous
one, ensuring that each layer is independently testable before adding complexity.

```
Phase 1: MVP — Auto Squad          Phase 2: Tactical C2
┌─────────────────────────┐        ┌─────────────────────────┐
│ F0  ✓ Mod loads         │        │ F2.1 WorldState reporter│
│ F1.1 ✓ Game to menu     │───────▶│ F2.2 LLM tactical router│
│ F1.2 Auto-squad spawn   │        │ F2.3 Waypoint execution │
│ F1.3 Route sync         │        │ F2.4 Rank + faction     │
└─────────┬───────────────┘        └─────────┬───────────────┘
          │                                  │
          ▼                                  ▼
Phase 3: Strategic AI               Phase 4: Full WarSim
┌─────────────────────────┐        ┌─────────────────────────┐
│ F3.1 Stavka orchestrator│        │ F4.1 LLM vs LLM loop    │
│ F3.2 OPFOR spawning     │        │ F4.2 Radio broadcast    │
│ F3.3 Feedback loop      │        │ F4.3 TTS squad replies  │
└─────────┬───────────────┘        │ F4.4 Persistent campaign│
          │                        └─────────────────────────┘
          ▼
     (Phases 3+4 overlap)
```

---

## Phase 1: MVP — Auto Squad

**Goal**: When a player joins the server, automatically spawn 5 AI squad members and
assign the player as squad leader. Bridge communication established.

### F0: Mod loads and compiles — ✅ DONE

| Task | Status | Verified |
|---|---|---|
| Create `addon.gproj` with GUID `7E5A1C9B3D8F2406` | ✅ | — |
| Create initial Enforce Script files | ✅ | — |
| Mod loads without engine initialization error | ✅ | console.log verified |
| No SCRIPT (E) in our script files | ✅ | console.log verified |

### F1.1: Game reaches main menu — ✅ DONE

| Task | Status | Verified |
|---|---|---|
| Client launches with mod via `-addonsDir` + `-addons` | ✅ | — |
| Game reaches main menu (not crash) | ✅ | console.log verified |
| `check_latest_log.ps1` reports `OK` | ✅ | — |

### F1.2: Component wiring + auto-squad — ✅ DONE (2026-08-09)

| Task | Status | Verified |
|---|---|---|
| `modded class SCR_PlayerController` with `OnControlledEntityChanged` hook | ✅ | console.log: `Player 1 entity changed` |
| `OnControlledEntityChanged` → `CallLater(DeferredAutoSquad, 5000)` | ✅ | console.log: `scheduling squad spawn (5s delay)` |
| `DeferredAutoSquad`: find group, `SetGroupLeader()`, `SetNumberOfMembersToSpawn(5)`, `SpawnUnits()` | ✅ | console.log: `SUCCESS: Auto-squad complete` |
| Faction matching via `SCR_FactionManager.GetPlayerFaction()` | ✅ | console.log: `Player faction: US` |
| `LLMBridge` instantiated via `modded SCR_BaseGameMode` + `CallLater` | ✅ | console.log: `LLM Bridge activated, periodic updates started` |
| `SCR_AIWorld` modded with static agent tracking | ✅ | console.log: `EOnInit FIRED`, `AddedAIAgent CALLED` |
| Test: `[AutoSquad] SUCCESS` appears in log | ✅ | All log evidence present |

**Key lessons learned:**
1. **Use Play (offline), NOT Host** — Host destroys game instance, mod not reloaded (5633 = vanilla)
2. **Use unpacked mods** — packed .pak files compile but modded classes don't execute at runtime
3. **`SCR_AIGroup.IsFull()` does NOT exist** — use `GetPlayerAndAgentCount()` vs `GetMaxMembers()`
4. **5s delay needed** — faction assignment + group init not ready at spawn time; 3s was too short

### F1.3: Route sync + e2e validation — 🔲 TODO

| Task | Status | Dependencies |
|---|---|---|
| Fix `/waypoint` mismatch (remove from LLMBridge.c or add to main.py) | 🔲 TODO | F1.2 |
| Fix `/status` method mismatch (POST→GET in LLMBridge.c) | 🔲 TODO | — |
| Add Pydantic schema for SITREP in main.py | 🔲 TODO | — |
| Add Pydantic schema for Command in main.py | 🔲 TODO | — |
| E2e test: game sends SITREP → bridge receives → bridge returns orders → game executes | 🔲 TODO | All above |

**Spec**: [REST Contracts](../api/rest-contracts.md)

---

## Phase 2: Tactical C2

**Goal**: Player sends text commands → LLM translates to JSON → game executes waypoints.
Latency: 2–5 seconds.

### F2.1: WorldState reporter (SITREP) — 🔲 TODO

| Task | Dependencies |
|---|---|
| Implement `LLMSquadAIRegistry` (modded `SCR_AIWorld` with agent tracking) | F1.2 |
| Build SITREP JSON from tracked agents + groups + objectives | — |
| `POST /sitrep` to bridge every 5 seconds via `CallLater` | — |
| Immediate SITREP on kill event (`RemovingAIAgent` override) | — |

**Spec**: [Data Flow — WorldState](../architecture/data-flow.md)

### F2.2: LLM tactical router — 🔲 TODO

| Task | Dependencies |
|---|---|
| `POST /api/c2/tactical` endpoint in main.py | F1.3 |
| Tactical system prompt construction | — |
| LLM call via `openai` Python client | — |
| JSON parsing + Pydantic validation of LLM output | — |
| Command queueing for `GET /orders` polling | — |
| 3-second timeout → HOLD fallback | — |

**Spec**: [Tactical C2](../design/tactical-c2.md)

### F2.3: Waypoint execution — 🔲 TODO

| Task | Dependencies |
|---|---|
| `GET /orders` polling in `LLMBridge.Update()` (every 2s) | F2.1 |
| Parse command JSON array | — |
| Create `AIWaypoint` at command position | — |
| `SCR_AIGroup.AddWaypointToGroup()` | — |
| Set formation, stance, combat mode | — |
| `POST /command/result` feedback to bridge | — |

**Spec**: [Tactical C2 — Execution](../design/tactical-c2.md)

### F2.4: Rank authority + faction isolation — 🔲 TODO

| Task | Dependencies |
|---|---|
| `SCR_ECharacterRank` check before command execution | F2.3 |
| Faction check: reject commands for non-BLUFOR groups | — |
| Priority stack implementation (CAPTAIN > SERGEANT > AI) | — |
| Guardrail logging (`[Guardrail]` prefix) | — |

**Spec**: [Tactical C2 — Rank Authority](../design/tactical-c2.md), [Guardrails](../design/guardrails.md)

---

## Phase 3: Strategic AI

**Goal**: OPFOR Stavka LLM reads full WorldState every 60–120s, decides objectives,
spawns OPFOR groups, sets waypoints.

### F3.1: Stavka LLM orchestrator — 🔲 TODO

| Task | Dependencies |
|---|---|
| `StavkaController` with `CallLater(StavkaCycle, 60000, true)` | F2.1 |
| Collect full WorldState (both factions) | F2.1 |
| `POST /api/stavka/strategic` to bridge | F1.3 |
| Strategic system prompt construction | — |
| LLM call with 30s timeout | — |
| OPORD JSON parsing + Pydantic validation | — |
| 30s timeout → maintain previous OPORD fallback | — |

**Spec**: [Strategic Stavka](../design/strategic-stavka.md)

### F3.2: OPFOR group spawning + waypoint assignment — 🔲 TODO

| Task | Dependencies |
|---|---|
| Parse OPORD orders array | F3.1 |
| Faction check: verify `faction == "USSR"` | — |
| AI limit check via `ChimeraAIWorld.CanLimitedAIBeAddedForFaction()` | — |
| `SCR_AIGroup.SpawnUnits()` for OPFOR | — |
| `AddWaypointToGroup()` with objective-based radius | — |
| `SetRadioFrequency()` for OPFOR groups | — |
| Fallback position waypoint | — |

**Spec**: [Strategic Stavka — Execution](../design/strategic-stavka.md)

### F3.3: Feedback loop — 🔲 TODO

| Task | Dependencies |
|---|---|
| Kill events trigger immediate WorldState update | F3.1 |
| Objective status changes trigger immediate SITREP | — |
| Casualty counting by faction | — |
| Significant OPFOR losses trigger early Stavka cycle | — |
| Stavka adapts force packages based on casualties | — |

**Spec**: [Data Flow — Feedback Loop](../architecture/data-flow.md)

---

## Phase 4: Full WarSim

**Goal**: LLM vs LLM closed loop with radio, voice, and persistent campaign state.

### F4.1: LLM vs LLM closed loop — 🔲 TODO

| Task | Dependencies |
|---|---|
| Both brains running simultaneously (Tactical BLUFOR + Stavka OPFOR) | F3.3 |
| Verify no namespace cross-contamination | — |
| Balance: tune OPFOR strength vs BLUFOR player skill | — |
| Automated scenario: no player needed (server-only simulation) | — |

### F4.2: Radio broadcast — 🔲 TODO

| Task | Dependencies |
|---|---|
| `SCR_AIGroup.SetRadioFrequency()` for all squads | F4.1 |
| Radio channel assignment per faction | — |
| LLM-generated radio messages (structured, not audio) | — |
| Radio message routing via frequency | — |

### F4.3: TTS for squad replies + OPFOR chatter — 🔲 TODO

| Task | Dependencies |
|---|---|
| TTS integration (text → audio) | F4.2 |
| Squad ack messages ("Roger, moving to hill 047") | — |
| OPFOR chatter (additive, not gameplay-critical) | — |
| Audio playback in-game | — |

### F4.4: Persistent campaign state — 🔲 TODO

| Task | Dependencies |
|---|---|
| Save campaign state to `$profile:campaign_state.json` | F4.1 |
| Load campaign state on server restart | — |
| OPORD history influences future Stavka decisions | — |
| Casualty tracking persists across sessions | — |
| Objective control history | — |

---

## Milestone Summary

| Milestone | Description | Status | Phase |
|---|---|---|---|
| F0 | Mod loads, compiles | ✅ DONE | 1 |
| F1.1 | Game reaches main menu | ✅ DONE | 1 |
| F1.2 | Auto-squad spawning | ✅ DONE | 1 |
| F1.3 | Route sync, e2e validation | 🔲 NEXT | 1 |
| F2.1 | WorldState reporter | 🔲 TODO | 2 |
| F2.2 | LLM tactical router | 🔲 TODO | 2 |
| F2.3 | Waypoint execution | 🔲 TODO | 2 |
| F2.4 | Rank + faction isolation | 🔲 TODO | 2 |
| F3.1 | Stavka orchestrator | 🔲 TODO | 3 |
| F3.2 | OPFOR spawning + waypoints | 🔲 TODO | 3 |
| F3.3 | Feedback loop | 🔲 TODO | 3 |
| F4.1 | LLM vs LLM closed loop | 🔲 TODO | 4 |
| F4.2 | Radio broadcast | 🔲 TODO | 4 |
| F4.3 | TTS squad replies | 🔲 TODO | 4 |
| F4.4 | Persistent campaign | 🔲 TODO | 4 |

---

## Dependencies

```
F0 ──→ F1.1 ──→ F1.2 ──→ F1.3 ──→ F2.1 ──→ F2.2 ──→ F2.3 ──→ F2.4
                                  │                              │
                                  └──→ F3.1 ──→ F3.2 ──→ F3.3 ──→ F4.1 ──→ F4.2 ──→ F4.3 ──→ F4.4
```

- F1.2 depends on F1.1 (game must reach main menu first)
- F1.3 depends on F1.2 (need component wiring for REST to work)
- F2.1 and F3.1 both depend on F1.3 (route sync must be done)
- F3.x can begin in parallel with F2.x completion (different brains, same infrastructure)
- F4.x requires both Phase 2 and Phase 3 complete

---

## Definition of Done

A milestone is "done" ONLY when:

1. **Code is implemented** and compiles without `SCRIPT (E)` in our files
2. **Game launches** and reaches the appropriate state (menu, server, etc.)
3. **`check_latest_log.ps1` reports `OK`**
4. **Feature-specific log lines appear** (e.g., `[LLMSquad] Auto-squad spawned`)
5. **In-game behavior is verified** (visual confirmation where applicable)
6. **No crashes** during a 5-minute play session

> "It compiles" ≠ "it works." Only empirical log evidence counts.
