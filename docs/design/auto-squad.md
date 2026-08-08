# F1.2 — Auto Squad Assignment Specification

> **Milestone**: F1.2 — Component wiring and automatic squad creation
> **Phase**: 1 (MVP)
> **Status**: 🔲 NEXT (not yet implemented)
> **Depends on**: F1.1 (game reaches main menu — ✅ DONE)

---

## Goal

When a player joins the server and their entity spawns, automatically:
1. Create an `SCR_AIGroup` entity near the player
2. Spawn 5 AI squad members
3. Add the player to the group
4. Set the player as the squad leader

This gives every player an AI squad on spawn, without manual setup.

---

## Implementation

### Entry point: SCR_PlayerController hook

We mod the `SCR_PlayerController` class to intercept `OnControlledEntityChanged()`.
This method fires whenever the player's controlled entity changes — including initial spawn,
respawn, and spectator transitions.

```c
modded class LLMSquadController
{
    // Override on modded SCR_PlayerController:
    override void OnControlledEntityChanged(IEntity from, IEntity to)
    {
        super.OnControlledEntityChanged(from, to);

        // ─── Server-only check ───
        // Auto-squad spawning must happen on the server.
        // The server owns AI spawning and group creation.
        if (!Replication.IsServer())
            return;

        // ─── Only trigger on spawn (entity becomes non-null) ───
        if (!to)
            return;  // player lost their entity (death/spectator) — skip

        int playerID = GetPlayerId();

        // ─── Delay to allow entity initialization ───
        // The player entity needs time to fully initialize (components, faction, position).
        // 3000ms is empirically sufficient; too short → faction/position may be null.
        GetGame().GetCallqueue().CallLater(
            AutoSquadSpawn,    // method
            3000,              // delay in ms
            false,             // repeat = false (one-time)
            playerID,          // arg 1
            to                 // arg 2 (player entity)
        );
    }
```

### Core method: AutoSquadSpawn

```c
    void AutoSquadSpawn(int playerID, IEntity playerEntity)
    {
        if (!playerEntity)
        {
            Print("[LLMSquad] AutoSquadSpawn: player entity is null, aborting");
            return;
        }

        // ─── Step 1: Get player's faction ───
        SCR_FactionManager factionMgr = SCR_FactionManager.Cast(
            GetGame().GetFactionManager());

        if (!factionMgr)
        {
            Print("[LLMSquad] AutoSquadSpawn: FactionManager not found");
            return;
        }

        Faction playerFaction = factionMgr.GetPlayerFaction(playerID);
        if (!playerFaction)
        {
            PrintFormat("[LLMSquad] AutoSquadSpawn: No faction for player %1",
                playerID);
            return;
        }

        // ─── Step 2: Get player position (with offset) ───
        vector playerPos = playerEntity.GetOrigin();
        vector spawnPos = playerPos + Vector(5, 0, 0);  // 5m offset

        // ─── Step 3: Read config (or use defaults) ───
        int squadSize = 5;
        int maxMembers = 6;  // 5 AI + 1 player
        int radioFreq = 150;
        SCR_ECharacterRank requiredRank = SCR_ECharacterRank.PRIVATE;

        // Try to read from $profile:agent_squad_config.json
        string configPath = "$profile:agent_squad_config.json";
        if (FileIO.FileExists(configPath))
        {
            SCR_JsonLoadContext loader = new SCR_JsonLoadContext();
            if (loader.LoadFromFile(configPath))
            {
                loader.ReadValue("squad_size", squadSize);
                loader.ReadValue("max_members", maxMembers);
                loader.ReadValue("radio_frequency", radioFreq);
                // Rank loaded as int, cast to enum
            }
        }

        // ─── Step 4: Check AI limit ───
        AIWorld aiWorld = GetGame().GetWorld().GetAIWorld();
        if (aiWorld)
        {
            int currentAI = aiWorld.GetCurrentNumOfActiveAIs();
            int aiLimit = aiWorld.GetAILimit();
            if (currentAI + squadSize > aiLimit)
            {
                PrintFormat("[LLMSquad] AutoSquadSpawn: AI limit reached " +
                    "(current=%1, limit=%2, needed=%3)", currentAI, aiLimit, squadSize);
                return;  // Don't crash, just skip
            }
        }

        // ─── Step 5: Create the SCR_AIGroup ───
        SCR_AIGroup group = SCR_AIGroup.Cast(
            GetGame().SpawnEntity(SCR_AIGroup, null, spawnPos));

        if (!group)
        {
            Print("[LLMSquad] AutoSquadSpawn: Failed to create SCR_AIGroup");
            return;
        }

        // ─── Step 6: Configure the group ───
        group.SetNumberOfMembersToSpawn(squadSize);
        group.SetMaxMembers(maxMembers);
        group.SetFaction(playerFaction);
        group.SetRadioFrequency(radioFreq);
        group.SetRequiredRank(requiredRank);

        // ─── Step 7: Spawn the AI units ───
        group.SpawnUnits();

        // ─── Step 8: Add player to group ───
        group.AddPlayer(playerID);

        // ─── Step 9: Set player as group leader ───
        group.SetGroupLeader(playerID);

        // ─── Step 10: Log result ───
        PrintFormat("[LLMSquad] Auto-squad spawned: %1 AI members, " +
            "player=%2 leader=true faction=%3 pos=%4",
            squadSize, playerID, playerFaction.GetFactionKey(), playerPos.ToString());
    }
```

### Failsafe handling

The entire method is wrapped in null checks. If any step fails:
- Log the error with `[LLMSquad]` prefix
- Return gracefully (do NOT throw or crash the game)
- The player simply has no auto-squad — they can still play

```c
        // Specific failsafe: if SpawnUnits() fails silently (returns void),
        // we verify via GetAIMembers() count:
        array<SCR_ChimeraCharacter> aiMembers = group.GetAIMembers();
        if (aiMembers.Count() < squadSize)
        {
            PrintFormat("[LLMSquad] AutoSquadSpawn: Only %1 of %2 AI spawned " +
                "(partial success)", aiMembers.Count(), squadSize);
            // Continue anyway — partial squad is better than none
        }
```

---

## Configuration

### Config file: `$profile:agent_squad_config.json`

```json
{
    "squad_size": 5,
    "max_members": 6,
    "radio_frequency": 150,
    "required_rank": 0,
    "spawn_offset_x": 5.0,
    "spawn_offset_z": 0.0
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `squad_size` | int | 5 | Number of AI members to spawn |
| `max_members` | int | 6 | Max group size (AI + players) |
| `radio_frequency` | int | 150 | Radio channel for the squad |
| `required_rank` | int | 0 | `SCR_ECharacterRank` value (0 = PRIVATE) |
| `spawn_offset_x` | float | 5.0 | X offset from player position for group spawn |
| `spawn_offset_z` | float | 0.0 | Z offset from player position for group spawn |

### Config loading pattern

```c
// Config is optional — defaults are used if file doesn't exist
string configPath = "$profile:agent_squad_config.json";

int squadSize = 5;  // default

if (FileIO.FileExists(configPath))
{
    SCR_JsonLoadContext loader = new SCR_JsonLoadContext();
    if (loader.LoadFromFile(configPath))
    {
        loader.ReadValue("squad_size", squadSize);
        // ... other fields
    }
}
```

### SCR_ECharacterRank enum values

| Value | Name |
|---|---|
| 0 | PRIVATE |
| 1 | CORPORAL |
| 2 | SERGEANT |
| 3 | LIEUTENANT |
| 4 | CAPTAIN |
| 5 | MAJOR |
| 6 | COLONEL |

---

## Testing Plan

### Prerequisites

1. Bridge running (`start_bridge.bat`)
2. Server launched with mod (`launch_reforger.bat` or dedicated server config)
3. Client connected to server

### Test steps

1. Player joins server
2. Wait ~3 seconds (CallLater delay)
3. Check console.log for `[LLMSquad] Auto-squad spawned:` line
4. Verify in-game: 5 AI squad members visible near the player
5. Verify player is squad leader (can issue orders)

### Log verification

```
[LLMSquad] Auto-squad spawned: 5 AI members, player=42 leader=true faction=US pos=4800.0, 0.0, 6300.0
```

### Failsafe tests

| Test | Expected behavior |
|---|---|
| AI limit reached | Log: `AI limit reached`, no crash, player continues without squad |
| FactionManager missing | Log: `FactionManager not found`, no crash |
| Player entity null after delay | Log: `player entity is null`, no crash |
| Config file missing | Use defaults (5 members, freq 150), log success |
| Config file malformed | `LoadFromFile` returns false, use defaults |

---

## Dependencies

| Dependency | Status | Notes |
|---|---|---|
| Mod loads in game | ✅ F0 | Verified |
| Game reaches main menu | ✅ F1.1 | Verified |
| `SCR_PlayerController` modded class compiles | 🔲 TODO | Must verify Enforce Script accepts `modded class SCR_PlayerController` |
| `SCR_AIGroup.SpawnUnits()` works on server | 🔲 TODO | Verify via test |
| `SCR_FactionManager.GetPlayerFaction()` returns valid faction | 🔲 TODO | Verify after 3s delay |
| `FileIO` + `SCR_JsonLoadContext` work with `$profile:` | 🔲 TODO | Test config loading |

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Player entity not fully initialized after 3s | Increase delay to 5000ms; or poll for faction availability |
| `SpawnUnits()` fails silently | Verify via `GetAIMembers().Count()` and log |
| Multiple players joining simultaneously | Each gets their own group; check AI limit globally |
| Player respawns (dies and comes back) | `OnControlledEntityChanged` fires again → new squad spawned. Consider checking if player already has a group to avoid duplicates |
| `modded class SCR_PlayerController` conflicts with other mods | Use unique method names; test for conflicts |

---

## Future extensions (post-F1.2)

- **Squad persistence**: Save squad state to `$profile:squad_state_<playerID>.json`
- **Squad customization**: Players configure squad size, faction via chat commands
- **Squad merge/split**: Merge two squads or split AI from player's squad
- **Squad death replacement**: Auto-respawn dead AI members to maintain squad strength
