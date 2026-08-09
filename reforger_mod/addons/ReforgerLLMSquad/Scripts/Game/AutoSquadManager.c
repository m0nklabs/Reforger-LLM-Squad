// AutoSquadManager.c - F1.2: Auto Squad Assignment + F2.x Live Orders
// When a player joins, automatically spawns an AI squad (5 members)
// and assigns the player as squad leader.
//
// F2.x: Static methods for live spawning via /orders endpoint
//
// Anti-hallucination: no invented APIs, no modclass, no nested classes.

//------------------------------------------------------------------------------------------------
// modded SCR_AIWorld: track AI agents + store player group for LLMBridge
modded class SCR_AIWorld
{
	protected static ref array<AIAgent> s_TrackedAgents = new array<AIAgent>();

	// F2: Store player's group for LLMBridge waypoint execution
	protected static SCR_AIGroup s_PlayerGroup;

	//------------------------------------------------------------------------------------------------
	override void AddedAIAgent(AIAgent agent)
	{
		super.AddedAIAgent(agent);
		if (agent && !s_TrackedAgents.Contains(agent))
			s_TrackedAgents.Insert(agent);
	}

	//------------------------------------------------------------------------------------------------
	override void RemovingAIAgent(AIAgent agent)
	{
		super.RemovingAIAgent(agent);
		s_TrackedAgents.RemoveItem(agent);
	}

	//------------------------------------------------------------------------------------------------
	override void EOnInit(IEntity owner)
	{
		super.EOnInit(owner);
		Print("[AutoSquad] SCR_AIWorld.EOnInit FIRED - modded class is alive");
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

	//------------------------------------------------------------------------------------------------
	static SCR_AIGroup GetPlayerGroup()
	{
		return s_PlayerGroup;
	}

	//------------------------------------------------------------------------------------------------
	static void SetPlayerGroup(SCR_AIGroup group)
	{
		s_PlayerGroup = group;
	}

	//------------------------------------------------------------------------------------------------
	// F2.x: Live spawn - called from LLMBridge when /orders cmd=spawn received
	static void LiveSpawnSquad(int playerID)
	{
		Print("[AutoSquad] LiveSpawnSquad called for player " + playerID);

		SCR_AIGroup grp = s_PlayerGroup;
		if (!grp)
		{
			Print("[AutoSquad] LiveSpawn: no stored group, trying to find it...");
			PlayerManager pm = GetGame().GetPlayerManager();
			if (!pm) { Print("[AutoSquad] LiveSpawn: no PlayerManager"); return; }
			IEntity playerEnt = pm.GetPlayerControlledEntity(playerID);
			if (!playerEnt) { Print("[AutoSquad] LiveSpawn: no player entity"); return; }

			AIControlComponent aiCtrl = AIControlComponent.Cast(playerEnt.FindComponent(AIControlComponent));
			if (aiCtrl)
			{
				AIAgent agent = aiCtrl.GetAIAgent();
				if (agent)
				{
					AIGroup rawGroup = agent.GetParentGroup();
					if (rawGroup)
					{
						grp = SCR_AIGroup.Cast(rawGroup);
						s_PlayerGroup = grp;
						Print("[AutoSquad] LiveSpawn: found group via AIControlComponent: " + grp);
					}
				}
			}
			if (!grp) { Print("[AutoSquad] LiveSpawn: could not find group"); return; }
		}

		int beforeCount = grp.GetPlayerAndAgentCount();
		int maxMembers = grp.GetMaxMembers();
		Print("[AutoSquad] LiveSpawn: group members=" + beforeCount + "/" + maxMembers);

		array<AIAgent> agents = {};
		grp.GetAgents(agents);
		if (agents.Count() > 0)
		{
			Print("[AutoSquad] LiveSpawn: already have " + agents.Count() + " AI agents, skipping");
			return;
		}

		// Try SpawnUnits
		grp.SetNumberOfMembersToSpawn(5);
		grp.SpawnUnits();
		Print("[AutoSquad] LiveSpawn: SpawnUnits() called");

		// Check result after 3s
		GetGame().GetCallqueue().CallLater(LiveSpawnCheck, 3000, false, playerID);
	}

	//------------------------------------------------------------------------------------------------
	static void LiveSpawnCheck(int playerID)
	{
		SCR_AIGroup grp = s_PlayerGroup;
		if (!grp) { Print("[AutoSquad] LiveSpawnCheck: no group"); return; }

		array<AIAgent> agents = {};
		grp.GetAgents(agents);
		int memberCount = grp.GetPlayerAndAgentCount();
		Print("[AutoSquad] LiveSpawnCheck: members=" + memberCount + " agents=" + agents.Count());

		if (agents.Count() == 0)
		{
			Print("[AutoSquad] LiveSpawnCheck: SpawnUnits failed, trying manual spawn...");
			LiveManualSpawn(grp, playerID);
		}
		else
		{
			Print("[AutoSquad] LiveSpawnCheck: SUCCESS - " + agents.Count() + " AI agents");
		}
	}

	//------------------------------------------------------------------------------------------------
	static void LiveManualSpawn(SCR_AIGroup grp, int playerID)
	{
		if (!grp) return;

		PlayerManager pm = GetGame().GetPlayerManager();
		if (!pm) { Print("[AutoSquad] LiveManual: no PlayerManager"); return; }
		IEntity playerEnt = pm.GetPlayerControlledEntity(playerID);
		if (!playerEnt) { Print("[AutoSquad] LiveManual: no player entity"); return; }

		vector playerPos = playerEnt.GetOrigin();
		vector playerDir = playerEnt.GetTransformAxis(0);

		Print("[AutoSquad] LiveManual: spawning 5 AI near " + playerPos);

		// Confirmed US soldier prefabs from vanilla SDK source (SCR_AutotestCommonFixture.c, SCR_CareerProfileHUD.c)
		array<ResourceName> prefabPaths = {};
		prefabPaths.Insert("{5B1996C05B1E51A4}Prefabs/Characters/Factions/BLUFOR/US_Army/Character_US_AR.et");
		prefabPaths.Insert("{2F912ED6E399FF47}Prefabs/Characters/Factions/BLUFOR/US_Army/Character_US_Unarmed.et");

		ResourceName usedPrefab = "";
		foreach (ResourceName pPath : prefabPaths)
		{
			Resource res = Resource.Load(pPath);
			if (res && res.IsValid())
			{
				usedPrefab = pPath;
				break;
			}
		}

		if (usedPrefab.IsEmpty())
		{
			Print("[AutoSquad] LiveManual: ALL prefab paths failed!");
			return;
		}

		Print("[AutoSquad] LiveManual: Using prefab " + usedPrefab);

		for (int i = 0; i < 5; i++)
		{
			vector offset = playerDir * (-3 - i * 2);
			vector spawnPos = playerPos + offset;
			spawnPos[1] = playerPos[1];

			EntitySpawnParams sp = new EntitySpawnParams();
			sp.TransformMode = ETransformMode.WORLD;
			sp.Transform[3] = spawnPos;

			IEntity aiEnt = GetGame().SpawnEntityPrefabEx(usedPrefab, true, GetGame().GetWorld(), sp);
			if (!aiEnt) { Print("[AutoSquad] LiveManual: failed to spawn entity #" + i); continue; }

			// Use AddAIEntityToGroup pattern from real SCR_AIGroup.c source:
			// 1. Find AIControlComponent
			// 2. Get GetControlAIAgent() (NOT GetAIAgent!)
			// 3. Call ActivateAI()
			// 4. AddAgent if no parent group yet
			AIControlComponent aiCtrl = AIControlComponent.Cast(aiEnt.FindComponent(AIControlComponent));
			if (!aiCtrl) { Print("[AutoSquad] LiveManual: no AIControlComponent on #" + i); continue; }

			AIAgent agent = aiCtrl.GetControlAIAgent();
			if (!agent) { Print("[AutoSquad] LiveManual: no AIAgent on #" + i); continue; }

			aiCtrl.ActivateAI();

			if (!agent.GetParentGroup())
				grp.AddAgent(agent);

			Print("[AutoSquad] LiveManual: AI #" + i + " spawned and added to group at " + spawnPos);
		}

		// Set formation so soldiers follow the leader
		AIFormationComponent formationComp = AIFormationComponent.Cast(grp.FindComponent(AIFormationComponent));
		if (formationComp)
		{
			formationComp.SetFormation("Column");
			Print("[AutoSquad] LiveManual: formation set to Column");
		}
		else
		{
			Print("[AutoSquad] LiveManual: WARNING - no AIFormationComponent on group!");
		}

		Print("[AutoSquad] LiveManual: Done, 5 AI spawned with formation");
	}

	//------------------------------------------------------------------------------------------------
	// F2.x: Set formation on the group
	static void SetGroupFormation(string formationName)
	{
		SCR_AIGroup grp = s_PlayerGroup;
		if (!grp) { Print("[AutoSquad] SetFormation: no group"); return; }

		AIFormationComponent formationComp = AIFormationComponent.Cast(grp.FindComponent(AIFormationComponent));
		if (formationComp)
		{
			formationComp.SetFormation(formationName);
			Print("[AutoSquad] SetFormation: " + formationName);
		}
		else
		{
			Print("[AutoSquad] SetFormation: no AIFormationComponent!");
		}
	}

	//------------------------------------------------------------------------------------------------
	// F2.x: Log group prefab slots - diagnostic for finding correct soldier prefab
	static void LogGroupPrefabs()
	{
		SCR_AIGroup grp = s_PlayerGroup;
		if (!grp) { Print("[AutoSquad] LogPrefabs: no group"); return; }

		Print("[AutoSquad] LogPrefabs: group=" + grp + " faction=" + grp.GetFactionName());
		Print("[AutoSquad] LogPrefabs: members=" + grp.GetPlayerAndAgentCount() + "/" + grp.GetMaxMembers());

		array<AIAgent> agents = {};
		grp.GetAgents(agents);
		Print("[AutoSquad] LogPrefabs: agents=" + agents.Count());
		for (int i = 0; i < agents.Count(); i++)
		{
			IEntity ent = agents[i].GetControlledEntity();
			if (ent)
				Print("[AutoSquad] LogPrefabs: agent[" + i + "] entity=" + ent + " prefab=" + ent.GetPrefabData().GetPrefabName());
		}
	}

	//------------------------------------------------------------------------------------------------
	// F2.x: Live despawn - remove all AI agents from group
	static void LiveDespawnSquad()
	{
		SCR_AIGroup grp = s_PlayerGroup;
		if (!grp) { Print("[AutoSquad] LiveDespawn: no group"); return; }

		array<AIAgent> agents = {};
		grp.GetAgents(agents);
		Print("[AutoSquad] LiveDespawn: removing " + agents.Count() + " AI agents");

		for (int i = agents.Count() - 1; i >= 0; i--)
		{
			AIAgent agent = agents[i];
			if (agent)
			{
				grp.RemoveAgent(agent);
				Print("[AutoSquad] LiveDespawn: removed agent #" + i);
			}
		}
		Print("[AutoSquad] LiveDespawn: done");
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

		if (!Replication.IsServer())
			return;
		if (!to)
			return;
		if (m_bAutoSquadDone && from)
			return;

		int playerID = GetPlayerId();
		if (playerID <= 0)
		{
			GetGame().GetCallqueue().CallLater(DeferredAutoSquad, 2000, false, playerID);
			return;
		}

		m_bAutoSquadDone = true;
		Print("[AutoSquad] Player " + playerID + " entity changed, scheduling squad spawn (5s delay)");
		GetGame().GetCallqueue().CallLater(DeferredAutoSquad, 5000, false, playerID);
	}

	//------------------------------------------------------------------------------------------------
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
			Print("[AutoSquad] No player entity found for player " + playerID);
			return;
		}

		// Get player faction
		SCR_FactionManager factionManager = SCR_FactionManager.Cast(GetGame().GetFactionManager());
		if (!factionManager)
		{
			Print("[AutoSquad] No faction manager");
			return;
		}
		Faction playerFaction = factionManager.GetPlayerFaction(playerID);
		if (!playerFaction)
		{
			Print("[AutoSquad] No player faction");
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

		// Method B: via AIControlComponent on player entity
		if (!scrGroup)
		{
			AIControlComponent aiCtrl = AIControlComponent.Cast(playerEntity.FindComponent(AIControlComponent));
			if (aiCtrl)
			{
				AIAgent playerAgent = aiCtrl.GetAIAgent();
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

			array<AIGroup> candidateGroups = {};
			int sameFactionCount = 0;
			int checkedAgents = 0;

			foreach (AIAgent agent : allAgents)
			{
				if (!agent) continue;
				checkedAgents++;

				AIGroup grp = agent.GetParentGroup();
				if (!grp) continue;
				if (candidateGroups.Contains(grp)) continue;

				SCR_AIGroup scrGrp = SCR_AIGroup.Cast(grp);
				if (!scrGrp) continue;

				string grpFaction = scrGrp.GetFactionName();
				if (grpFaction != factionKey) continue;

				sameFactionCount++;

				// Skip player-led groups
				int leaderID = scrGrp.GetFirstPlayerLeaderID();
				if (leaderID != 0) continue;

				candidateGroups.Insert(grp);

				int currentCount = scrGrp.GetPlayerAndAgentCount();
				int maxMembers = scrGrp.GetMaxMembers();
				Print("[AutoSquad] Candidate group: faction=" + grpFaction + " count=" + currentCount + " max=" + maxMembers);

				if (currentCount < maxMembers)
				{
					scrGroup = scrGrp;
					Print("[AutoSquad] Selected faction group for player");
					break;
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

			// Ensure enough room
			int currentMax = scrGroup.GetMaxMembers();
			scrGroup.SetMaxMembers(10);
			Print("[AutoSquad] MaxMembers set to 10 (was " + currentMax + ")");

			// Spawn 5 AI units into the group
			int beforeCount = scrGroup.GetPlayerAndAgentCount();
			Print("[AutoSquad] Members BEFORE spawn: " + beforeCount + "/10");

			scrGroup.SetNumberOfMembersToSpawn(5);
			Print("[AutoSquad] SetNumberOfMembersToSpawn(5)");

			scrGroup.SpawnUnits();
			Print("[AutoSquad] SpawnUnits() called - 5 AI should spawn near group");

			// Check result after 10s (SpawnUnits may be async)
			GetGame().GetCallqueue().CallLater(SCR_AIWorld.LiveSpawnCheck, 10000, false, playerID);

			// F2: Store group reference for LLMBridge waypoint execution
			SCR_AIWorld.SetPlayerGroup(scrGroup);

			Print("[AutoSquad] SUCCESS: Auto-squad complete for player " + playerID);
		}
		else
		{
			Print("[AutoSquad] No suitable group found. Player will play solo.");
		}
	}
};
