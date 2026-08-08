# Data Flow Diagrams

> Detailed data flow for all major operations in the Reforger LLM WarSim system.
> See [Architecture Overview](overview.md) for the high-level layer description.

---

## 1. WorldState Reporting (SITREP)

The game mod periodically collects the current world state and pushes it to the bridge.
This is the primary input for both the Tactical and Strategic brains.

```
┌─────────────────────────── GAME SERVER ───────────────────────────┐
│                                                                   │
│  SCR_AIWorld                                                      │
│  ├── AAC_GetTrackedAgents() ──→ array<AIAgent>                   │
│  │   (all AI agents in the world)                                │
│  │                                                                │
│  ├── For each AIAgent:                                           │
│  │   ├── FactionAffiliationComponent.GetAffiliatedFaction()      │
│  │   ├── RplComponent.Id() ──→ RplId (network ID)               │
│  │   ├── GetOrigin() ──→ position [x, y, z]                      │
│  │   └── Build agent state: {id, faction, position, alive}        │
│  │                                                                │
│  ├── SCR_AIGroup.GetWaypoints() ──→ current objectives           │
│  │                                                                │
│  └── Assemble SITREP JSON:                                       │
│      {                                                           │
│        "timestamp": "2026-08-08T21:26:00Z",                      │
│        "faction": "US",                                          │
│        "squad_states": [                                         │
│          {"squad_id": "...", "leader": "...",                    │
│           "members": 5, "position": [x,y,z],                    │
│           "status": "MOVING", "waypoint": [x,y,z]}               │
│        ],                                                        │
│        "objectives": [                                           │
│          {"id": "...", "type": "SEIZE", "position": [x,y,z],     │
│           "status": "IN_PROGRESS"}                               │
│        ]                                                         │
│      }                                                           │
│                                                                   │
│  LLMBridge                                                       │
│  ├── RestContext ctx = GetGame().GetRestApi()                    │
│  │       .GetContext("http://127.0.0.1:5001")                   │
│  ├── LLMBridgeCallback cb = new LLMBridgeCallback()              │
│  └── ctx.POST(cb, "/sitrep", sitrepJsonString)                   │
│         │ (async, non-blocking)                                  │
└─────────┼───────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────── BRIDGE (FastAPI) ─────────────────────┐
│                                                                   │
│  @app.post("/sitrep")                                            │
│  async def sitrep(request: SitrepRequest):                       │
│      # Pydantic validates the JSON                               │
│      # Store in world_state singleton                            │
│      world_state.update(request)                                 │
│      return {"status": "ack"}                                    │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### REST transport details

```c
// Enforce Script — how the REST call works internally:
RestContext ctx = GetGame().GetRestApi().GetContext(url);
// ctx is NOT a new RestContext() — that does NOT exist in Reforger
// GetContext() returns a managed context tied to the given URL

ctx.POST(cb, path, body);
// cb: RestCallback subclass — OnSuccess(data, size), OnError(code), OnTimeout()
// path: string (e.g. "/sitrep")
// body: string (pre-serialized JSON)

ctx.GET(cb, path);
// Same callback mechanism, no body
```

---

## 2. Tactical Command Flow (BLUFOR)

The Tactical brain responds to player commands. Latency target: 2–5 seconds.

```
┌─────────────────── PLAYER INPUT ───────────────────┐
│                                                     │
│  Player types: "Squad, move to the hill at grid     │
│  047 126, keep low, wedge formation"                │
│                                                     │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────── GAME SERVER (Enforce Script) ───┐
│                                                     │
│  LLMSquadController                                 │
│  ├── Capture player text + current SITREP          │
│  ├── Build command JSON:                            │
│  │   {"text": "move to hill...",                  │
│  │    "context": { <squad_positions>,              │
│  │                 <enemy_contacts>,               │
│  │                 <current_waypoints> }}          │
│  └── POST /api/c2/tactical                          │
│                                                     │
└──────────────────────┬──────────────────────────────┘
                       │ (async REST via RestCallback)
                       ▼
┌─────────────────── BRIDGE (FastAPI) ───────────────┐
│                                                     │
│  @app.post("/api/c2/tactical")                    │
│  async def tactical_command(request):              │
│      # Build LLM prompt with tactical system prompt │
│      prompt = TACTICAL_SYSTEM_PROMPT               │
│              + json.dumps(request.context)         │
│              + request.text                        │
│                                                     │
│      # Call LLM via OpenAI client                  │
│      response = openai_client.chat.completions     │
│          .create(model="llama3",                   │
│                   messages=[{"role":"system",       │
│                             "content": prompt}],   │
│                   temperature=0.3)                  │
│                                                     │
│      # Parse LLM output as JSON                    │
│      command = json.loads(response.choices[0]       │
│                             .message.content)      │
│                                                     │
│      # Pydantic validation                         │
│      validated = TacticalCommand(**command)        │
│                                                     │
│      # Queue for game to poll                      │
│      command_queue.put(validated)                  │
│      return {"status": "queued",                   │
│              "command_id": "..."}                   │
│                                                     │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────── LLM (Ollama llama3) ─────────────┐
│                                                     │
│  System prompt: "You are a tactical AI commander   │
│  for a BLUFOR squad in Arma Reforger. Translate     │
│  the player's order into a JSON command with        │
│  fields: action, position [x,y,z], formation,      │
│  stance, combat_mode."                             │
│                                                     │
│  Output (JSON):                                     │
│  {                                                  │
│    "action": "MOVE",                               │
│    "position": [4800.0, 0.0, 6300.0],             │
│    "formation": "WEDGE",                           │
│    "stance": "CROUCH",                             │
│    "combat_mode": "HOLD_FIRE"                      │
│  }                                                  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Game polls for the command

```
┌─────────────────── GAME SERVER ─────────────────────┐
│                                                      │
│  LLMBridge.Update() (via CallLater, repeat=true)    │
│  ├── RestContext ctx (cached)                       │
│  ├── ctx.GET(generalCallback, "/orders")             │
│  └── RestCallback.OnSuccess(data):                  │
│      ├── Parse JSON array of commands               │
│      ├── For each command:                           │
│      │   ├── Validate squad_id is BLUFOR            │
│      │   ├── Create AIWaypoint at position           │
│      │   │   wp.SetCompletionRadius(15.0)            │
│      │   │   wp.SetCompletionType(...)               │
│      │   │   wp.SetPriorityLevel(1.0)                │
│      │   ├── SCR_AIGroup.AddWaypointToGroup(wp)      │
│      │   └── POST /command/result (success/fail)    │
│      └── Done                                        │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Execution: SCR_AIGroup.AddWaypointToGroup()

```c
// Enforce Script — waypoint execution (verified API)
AIWaypoint wp = AIWaypoint.Cast(
    GetGame().SpawnEntity(AIWaypoint, null, coords));

if (wp) {
    wp.SetCompletionRadius(15.0);
    wp.SetCompletionType(EAIWaypointCompletionType.All);
    wp.SetPriorityLevel(1.0);
}

SCR_AIGroup group = ...; // find the squad
if (group && wp) {
    group.AddWaypointToGroup(wp);
    // The AI group will now navigate to the waypoint
}
```

---

## 3. Strategic Command Flow (OPFOR Stavka)

The Strategic brain runs on a timer, not on player input. Latency target: 60–120s.

```
┌─────────────────── GAME SERVER ─────────────────────┐
│                                                      │
│  StavkaController (timer via CallLater, 60s repeat)│
│  │                                                   │
│  ├── 1. Collect full WorldState                     │
│  │   ├── SCR_AIWorld.GetAIAgents(out agents)        │
│  │   ├── For each agent: faction, position, alive  │
│  │   ├── All objectives + status                    │
│  │   └── All group waypoints                        │
│  │                                                   │
│  ├── 2. POST /api/stavka/strategic                  │
│  │   Body: { "world_state": { <full snapshot> },    │
│  │           "faction": "USSR" }                    │
│  │                                                   │
│  ├── 3. (async) Wait for RestCallback.OnSuccess     │
│  │                                                   │
│  └── 4. On response: parse OPORD JSON               │
│      ├── For each order in OPORD:                    │
│      │   ├── SCR_AIGroup group = SpawnGroup(...)    │
│      │   ├── group.SetNumberOfMembersToSpawn(N)     │
│      │   ├── group.SetFaction(opforFaction)         │
│      │   ├── group.SpawnUnits()                     │
│      │   ├── AIWaypoint wp = CreateWaypoint(pos)    │
│      │   ├── group.AddWaypointToGroup(wp)           │
│      │   └── group.SetRadioFrequency(channel)       │
│      └── Log: "[Stavka] OPORD executed: N groups"  │
│                                                      │
└──────────────────────────────────────────────────────┘
                       │
                       ▼ (REST POST, async)
┌─────────────────── BRIDGE (FastAPI) ────────────────┐
│                                                      │
│  @app.post("/api/stavka/strategic")                 │
│  async def strategic_command(request):              │
│      prompt = STRATEGIC_SYSTEM_PROMPT               │
│              + json.dumps(request.world_state)      │
│              + "Generate an OPORD with objectives,  │
│                 force packages, timing, fallback."  │
│                                                      │
│      response = openai_client.chat.completions      │
│          .create(model="llama3",                    │
│                   messages=[...],                    │
│                   temperature=0.5,                   │
│                   max_tokens=2000)                   │
│                                                      │
│      opord = json.loads(response.choices[0]          │
│                          .message.content)          │
│      validated = StrategicOpord(**opord)            │
│      command_queue.put(validated)                   │
│      return {"status": "queued"}                     │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### OPORD output format

```json
{
  "opord_id": "STAVKA-2026-0808-001",
  "timestamp": "2026-08-08T21:26:00Z",
  "faction": "USSR",
  "orders": [
    {
      "objective": "SEIZE",
      "location": [4800.0, 0.0, 6300.0],
      "force_package": {
        "group_type": "RIFLE_SQUAD",
        "member_count": 8,
        "faction": "USSR"
      },
      "timing": "IMMEDIATE",
      "fallback": "DEFEND at [4500.0, 0.0, 6000.0]"
    },
    {
      "objective": "DEFEND",
      "location": [3500.0, 0.0, 4200.0],
      "force_package": {
        "group_type": "MACHINE_GUN_TEAM",
        "member_count": 4,
        "faction": "USSR"
      },
      "timing": "HOLD",
      "fallback": "WITHDRAW to [3000.0, 0.0, 4000.0]"
    }
  ]
}
```

### Execution: SCR_AIGroup.SpawnUnits() + AddWaypointToGroup()

```c
// Enforce Script — strategic group spawning (verified API)
SCR_AIGroup group = SCR_AIGroup.Cast(
    GetGame().SpawnEntity(SCR_AIGroup, null, spawnCoords));

if (group) {
    group.SetNumberOfMembersToSpawn(order.member_count);
    group.SetMaxMembers(order.member_count + 1);
    group.SetFaction(opforFaction);
    group.SetRadioFrequency(radioChannel);
    group.SetRequiredRank(SCR_ECharacterRank.SERGEANT);
    group.SpawnUnits();

    AIWaypoint wp = AIWaypoint.Cast(
        GetGame().SpawnEntity(AIWaypoint, null, order.location));
    if (wp) {
        wp.SetCompletionRadius(25.0);
        wp.SetCompletionType(EAIWaypointCompletionType.All);
        wp.SetPriorityLevel(1.0);
        group.AddWaypointToGroup(wp);
    }
}
```

---

## 4. Feedback Loop (Kill Events → Adaptation)

Both brains adapt based on battlefield events. The feedback loop ensures the LLMs
receive updated information after each significant event.

```
┌──────────────────────────────────────────────────────────┐
│                                                           │
│  KILL EVENT (entity destroyed)                            │
│  ├── SCR_AIWorld.RemovingAIAgent(agent)                  │
│  ├── Update WorldState: mark agent as KIA               │
│  ├── Recalculate squad_states (members count)           │
│  └── POST /sitrep (immediate update, not wait for timer)│
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │                                                     │ │
│  │  ┌─── TACTICAL BRAIN ──────┐  ┌── STRATEGIC BRAIN ┐│ │
│  │  │                          │  │                   ││ │
│  │  │ Next player command      │  │ Next Stavka cycle ││ │
│  │  │ includes updated SITREP  │  │ (≤60s) reads     ││ │
│  │  │ with new casualty count  │  │ updated WorldState││ │
│  │  │                          │  │ with casualties   ││ │
│  │  │ LLM adapts:              │  │                   ││ │
│  │  │ "Squad is at 3/5         │  │ LLM adapts:       ││ │
│  │  │  strength, recommend     │  │ "OPFOR lost 2     ││ │
│  │  │  DEFEND not MOVE"        │  │  squads, reinforce││ │
│  │  │                          │  │  at grid 047"     ││ │
│  │  └──────────────────────────┘  └───────────────────┘│ │
│  │                                                     │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

### Kill event handling

```c
// Enforce Script — modded SCR_AIWorld to track agent removals
modded class SCR_AIWorld
{
    override void RemovingAIAgent(AIAgent agent)
    {
        super.RemovingAIAgent(agent);

        // Update our tracking
        Faction faction = FactionAffiliationComponent
            .Cast(agent.GetInformation().GetComponent(
                FactionAffiliationComponent))
            .GetAffiliatedFaction();

        // Trigger immediate SITREP update
        LLMBridge bridge = LLMBridge.GetInstance();
        if (bridge) {
            bridge.QueueSITREP(); // marks SITREP dirty for next update tick
        }

        PrintFormat("[LLMSquad] Agent killed: faction=%1",
            faction.GetFactionKey());
    }
}
```

---

## 5. REST Transport Summary

### Verified REST API pattern (Enforce Script)

```c
// ─── 1. Get the REST API singleton and create a context ───
RestApi restApi = GetGame().GetRestApi();
RestContext ctx = restApi.GetContext("http://127.0.0.1:5001");

// ─── 2. Define a callback class ───
class LLMBridgeCallback : RestCallback
{
    ref string m_expectedId; // optional context for matching request→response

    override void OnSuccess(string data, int dataSize)
    {
        // data = response body as string
        // Parse JSON, execute command, etc.
        PrintFormat("[LLMBridge] Response received: %1 bytes", dataSize);
    }

    override void OnError(int errorCode)
    {
        // errorCode = HTTP error code
        PrintFormat("[LLMBridge] Error: code=%1", errorCode);
        // Fallback: HOLD position or maintain previous OPORD
    }

    override void OnTimeout()
    {
        Print("[LLMBridge] Request timed out");
        // Fallback: HOLD position or maintain previous OPORD
    }
}

// ─── 3. Issue requests (non-blocking) ───
LLMBridgeCallback cb = new LLMBridgeCallback();
ctx.POST(cb, "/sitrep", jsonBody);
ctx.GET(cb, "/orders");
```

### What does NOT work (anti-hallucination)

| Pattern | Status | Correction |
|---|---|---|
| `new RestContext()` | ❌ Does not exist | `GetGame().GetRestApi().GetContext(url)` |
| `ctx.SetURL(url)` | ❌ Does not exist | URL is set at `GetContext()` time |
| `ctx.SetMethod(RestMethod.POST)` | ❌ Does not exist | Use `ctx.POST()` or `ctx.GET()` directly |
| `ctx.SetBody(jsonStr)` | ❌ Does not exist | Body is 3rd argument to `ctx.POST(cb, path, body)` |
| `ctx.Start()` | ❌ Does not exist | `POST()` and `GET()` return immediately (async) |
| `ref RestContext` | ❌ Invalid type | Use `RestContext` (no `ref` keyword on this type) |
