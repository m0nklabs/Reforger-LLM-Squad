// AutoSquadManager.c - F1.2: Auto Squad Assignment
//
// When a player joins the server, automatically spawns an AI squad (5 members)
// and assigns the player as squad leader.
//
// APPROACH: Use SCR_AIGroup.SetNumberOfMembersToSpawn() + SpawnUnits()
// to spawn FRESH AI into the player's group, not recruit existing AI.
//
// Key APIs (all verified against Doxygen):
//   SCR_PlayerControllerGroupComponent.GetPlayersGroup()  — get player's AIGroup
//   SCR_AIGroup.SetGroupLeader(int playerID)  — player becomes leader
//   SCR_AIGroup.SetNumberOfMembersToSpawn(int)  — AI count
//   SCR_AIGroup.SpawnUnits()  — spawn AI members
//   SCR_AIGroup.SetMaxMembers(int)  — group size limit
//   SCR_AIGroup.AddPlayer(int playerID)  — add player to group
//   SCR_AIGroup.GetFactionName()  — faction key string
//   SCR_AIGroup.GetPlayerAndAgentCount()  — total members (replaces non-existent IsFull())
//   SCR_AIGroup.GetMaxMembers()  — max capacity
//   SCR_FactionManager.GetPlayerFaction(playerID)  — faction lookup
//   SCR_AIWorld.AddedAIAgent/RemovingAIAgent  — agent registry
//
// Anti-hallucination: no invented APIs, no modclass, no nested classes.

//------------------------------------------------------------------------------------------------
// modded SCR_AIWorld: track all AI agents globally (for SITREP reporting)
modded class SCR_AIWorld
{
	protected static ref array<AIAgent> s_TrackedAgents = new array<AIAgent>();

	//------------------------------------------------------------------------------------------------
	override void EOnInit(IEntity owner)
	{
		super.EOnInit(owner);
		Print("[AutoSquad] SCR_AIWorld.EOnInit FIRED — modded class is alive");
	}

	//------------------------------------------------------------------------------------------------
	override void AddedAIAgent(AIAgent agent)
	{
		super.AddedAIAgent(agent);
		if (agent && !s_TrackedAgents.Contains(agent))
		{
			s_TrackedAgents.Insert(agent);
		}
	}

	//------------------------------------------------------------------------------------------------
	override void RemovingAIAgent(AIAgent agent)
	{
		super.RemovingAIAgent(agent);
		if (agent)
		{
			s_TrackedAgents.RemoveItem(agent);
		}
	}

	//------------------------------------------------------------------------------------------------
	static void GetTrackedAgents(out notnull array<AIAgent> outAgents)
	{
		outAgents.Copy(s_TrackedAgents);
	}

	//------------------------------------------------------------------------------------------------
	static int GetTrackedAgentCount()
	{
		return s_TrackedAgents.Count();
	}
}

//------------------------------------------------------------------------------------------------
// modded SCR_PlayerController: hook on player spawn to trigger auto-squad
modded class SCR_PlayerController
{
	protected bool m_bAutoSquadDone = false;

	//------------------------------------------------------------------------------------------------
	override void OnControlledEntityChanged(IEntity from, IEntity to)
	{
		super.OnControlledEntityChanged(from, to);

		// Only run on server (authority)
		if (!Replication.IsServer())
			return;

		// Player entity just assigned?
		if (!to)
			return;

		// Already done for this controller? Reset on respawn (from=null means new entity)
		if (m_bAutoSquadDone && from)
			return;

		int playerID = GetPlayerId();
		if (playerID <= 0)
		{
			Print("[AutoSquad] WARNING: OnControlledEntityChanged but playerId <= 0, retrying...");
			GetGame().GetCallqueue().CallLater(DeferredAutoSquad, 2000, false, playerID);
			return;
		}

		Print("[AutoSquad] Player " + playerID + " entity changed, scheduling squad spawn (5s delay)");
		m_bAutoSquadDone = true;
		// 5 second delay — let faction assignment + group init complete first
		GetGame().GetCallqueue().CallLater(DeferredAutoSquad, 5000, false, playerID);
	}

	//------------------------------------------------------------------------------------------------
	// Deferred spawn: waits for player entity + faction to be fully initialized
	void DeferredAutoSquad(int playerID)
	{
		Print("[AutoSquad] DeferredAutoSquad starting for player " + playerID);

		if (!Replication.IsServer())
		{
			Print("[AutoSquad] Not server, aborting");
			return;
		}

		// Get player controlled entity
		IEntity playerEntity = GetGame().GetPlayerManager().GetPlayerControlledEntity(playerID);
		if (!playerEntity)
		{
			Print("[AutoSquad] ERROR: player entity not found for playerID " + playerID);
			return;
		}

		// Get player faction
		SCR_FactionManager fm = SCR_FactionManager.Cast(GetGame().GetFactionManager());
		if (!fm)
		{
			Print("[AutoSquad] ERROR: no FactionManager");
			return;
		}

		Faction playerFaction = fm.GetPlayerFaction(playerID);
		if (!playerFaction)
		{
			Print("[AutoSquad] ERROR: player faction is null");
			return;
		}

		string factionKey = playerFaction.GetFactionKey();
		Print("[AutoSquad] Player faction: " + factionKey);

		// Get player's group controller component
		SCR_PlayerControllerGroupComponent groupComp = SCR_PlayerControllerGroupComponent.Cast(
			FindComponent(SCR_PlayerControllerGroupComponent));

		if (!groupComp)
		{
			Print("[AutoSquad] WARNING: no SCR_PlayerControllerGroupComponent found");
		}

		// --- STEP 1: Try to get the player's existing group ---
		SCR_AIGroup scrGroup = null;

		// Method A: via group component
		if (groupComp)
		{
			AIGroup rawGroup = groupComp.GetPlayersGroup();
			if (rawGroup)
			{
				scrGroup = SCR_AIGroup.Cast(rawGroup);
				Print("[AutoSquad] Found player group via groupComp: " + scrGroup);
			}
		}

		// Method B: via AIControlComponent on the player entity
		if (!scrGroup)
		{
			AIControlComponent aiCtrl = AIControlComponent.Cast(playerEntity.FindComponent(AIControlComponent));
			if (aiCtrl)
			{
				AIAgent playerAgent = aiCtrl.GetControlAIAgent();
				if (playerAgent)
				{
					AIGroup rawGroup = playerAgent.GetParentGroup();
					if (rawGroup)
					{
						scrGroup = SCR_AIGroup.Cast(rawGroup);
						Print("[AutoSquad] Found player group via AIControlComponent: " + scrGroup);
					}
				}
			}
		}

		// --- STEP 2: If player has no group, find a same-faction AI group ---
		if (!scrGroup)
		{
			Print("[AutoSquad] No player group found, searching for faction groups...");

			array<AIAgent> allAgents = {};
			SCR_AIWorld.GetTrackedAgents(allAgents);
			Print("[AutoSquad] Total tracked agents: " + allAgents.Count());

			// Collect unique groups of same faction
			array<AIGroup> candidateGroups = {};
			int sameFactionCount = 0;
			int checkedAgents = 0;

			foreach (AIAgent agent : allAgents)
			{
				if (!agent)
					continue;

				checkedAgents++;

				AIGroup grp = agent.GetParentGroup();
				if (!grp)
					continue;

				// Skip if already in candidate list
				if (candidateGroups.Contains(grp))
					continue;

				SCR_AIGroup scrGrp = SCR_AIGroup.Cast(grp);
				if (!scrGrp)
					continue;

				// Check faction
				string grpFaction = scrGrp.GetFactionName();
				if (grpFaction != factionKey)
					continue;

				sameFactionCount++;

				// Skip player-led groups
				if (scrGrp.GetFirstPlayerLeaderID() > 0)
					continue;

				// Check capacity (IsFull() does NOT exist — use count vs max)
				int currentCount = scrGrp.GetPlayerAndAgentCount();
				int maxMembers = scrGrp.GetMaxMembers();
				Print("[AutoSquad] Candidate group: faction=" + grpFaction + " count=" + currentCount + " max=" + maxMembers);

				candidateGroups.Insert(grp);

				// Use the first suitable one
				if (!scrGroup)
				{
					scrGroup = scrGrp;
					Print("[AutoSquad] Selected faction group for player");
				}
			}

			Print("[AutoSquad] Checked " + checkedAgents + " agents, " + sameFactionCount + " same-faction, " + candidateGroups.Count() + " candidates");
		}

		// --- STEP 3: Add player to group if found, then spawn AI ---
		if (scrGroup)
		{
			Print("[AutoSquad] Using group: " + scrGroup + " faction=" + scrGroup.GetFactionName());

			// Add player to the group if not already in it
			if (!scrGroup.IsPlayerInGroup(playerID))
			{
				scrGroup.AddPlayer(playerID);
				Print("[AutoSquad] Player " + playerID + " added to group");
			}

			// Set player as group leader
			scrGroup.SetGroupLeader(playerID);
			Print("[AutoSquad] Player " + playerID + " set as group leader");

			// Ensure enough room for 5 AI + player
			int currentMax = scrGroup.GetMaxMembers();
			if (currentMax < 6)
			{
				scrGroup.SetMaxMembers(10);
				Print("[AutoSquad] MaxMembers increased from " + currentMax + " to 10");
			}

			// Spawn 5 AI units into the group
			scrGroup.SetNumberOfMembersToSpawn(5);
			Print("[AutoSquad] SetNumberOfMembersToSpawn(5)");

			scrGroup.SpawnUnits();
			Print("[AutoSquad] SpawnUnits() called — 5 AI should spawn near group");

			Print("[AutoSquad] SUCCESS: Auto-squad complete for player " + playerID);
		}
		else
		{
			Print("[AutoSquad] No suitable group found. Attempting to create one via group component...");

			// Last resort: try RequestAddAIAgent on nearby AI
			if (groupComp)
			{
				vector playerPos = playerEntity.GetOrigin();
				Print("[AutoSquad] Player position: " + playerPos.ToString());

				// Search a wider area for any same-faction AI (not just recruitable)
				array<AIAgent> nearbyAgents = {};
				SCR_AIWorld.GetTrackedAgents(nearbyAgents);

				int recruited = 0;
				foreach (AIAgent agent : nearbyAgents)
				{
					if (recruited >= 5)
						break;

					if (!agent)
						continue;

					IEntity aiEntity = agent.GetControlledEntity();
					if (!aiEntity)
						continue;

					// Must be same faction
					FactionAffiliationComponent facComp = FactionAffiliationComponent.Cast(
						aiEntity.FindComponent(FactionAffiliationComponent));
					if (!facComp)
						continue;

					Faction aiFaction = facComp.GetAffiliatedFaction();
					if (!aiFaction || aiFaction.GetFactionKey() != factionKey)
						continue;

					// Must be recruitable
					SCR_ChimeraCharacter character = SCR_ChimeraCharacter.Cast(aiEntity);
					if (!character || !character.IsRecruitable())
						continue;

					// Must be alive
					CharacterControllerComponent cc = CharacterControllerComponent.Cast(
						aiEntity.FindComponent(CharacterControllerComponent));
					if (cc && cc.IsDead())
						continue;

					// Skip player-controlled entities
					if (GetGame().GetPlayerManager().GetPlayerIdFromControlledEntity(aiEntity) != 0)
						continue;

					// Recruit this AI!
					groupComp.RequestAddAIAgent(character, playerID);
					recruited++;
					Print("[AutoSquad] Recruited AI #" + recruited + ": " + character);
				}

				if (recruited > 0)
				{
					Print("[AutoSquad] SUCCESS: Recruited " + recruited + " AI squad members for player " + playerID);
				}
				else
				{
					Print("[AutoSquad] WARNING: No recruitable AI found nearby. Player will play solo.");
				}
			}
			else
			{
				Print("[AutoSquad] FAILED: No group component, no group found, cannot recruit.");
			}
		}
	}
}
