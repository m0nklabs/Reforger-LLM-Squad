// AutoSquadManager.c - F1.2: Auto Squad Assignment + F2.x Live Orders
// When a player joins, automatically spawns an AI squad (5 members)
// and assigns the player as squad leader.
//
// F2.x: Static methods for live spawning via /orders endpoint
//
// Anti-hallucination: no invented APIs, no modclass, no nested classes.

//------------------------------------------------------------------------------------------------
// F4: Module-level entity query callback for vehicle search
ref array<IEntity> g_aQueriedEntities = {};
bool QueryEntityCallback(IEntity ent)
{
	if (ent) g_aQueriedEntities.Insert(ent);
	return true;
}

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
	static vector GetBLUFORPosition()
	{
		// Method 1: stored player group
		SCR_AIGroup grp = SCR_AIGroup.Cast(s_PlayerGroup);
		if (grp)
		{
			vector origin = grp.GetOrigin();
			if (origin != "0 0 0")
				return origin;
		}

		// Method 2: iterate all players 1-32 (same pattern as LLMBridge.FindPlayerGroup)
		PlayerManager pm = GetGame().GetPlayerManager();
		if (pm)
		{
			for (int pid = 1; pid <= 32; pid++)
			{
				IEntity pEnt = pm.GetPlayerControlledEntity(pid);
				if (pEnt)
					return pEnt.GetOrigin();
			}
		}

		return "0 0 0";
	}

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

		// Ensure slave group exists and get it
		SCR_AIGroup slaveGroup = EnsureSlaveGroup(grp);
		if (!slaveGroup)
		{
			Print("[AutoSquad] LiveManual: Failed to create slave group! Cannot add AI.");
			return;
		}

		Print("[AutoSquad] LiveManual: Using slave group: " + slaveGroup);

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

			// Use AddAgentFromControlledEntity pattern:
			// This is the vanilla pattern from SCR_PlayerControllerGroupComponent.AddAIToSlaveGroup()
			// Use AddAgentFromControlledEntity pattern (vanilla MP pattern):
			// This calls OnGroupMemberStateChange() which broadcasts via RplRpc to clients
			// IMPORTANT: Do NOT call ActivateAI() before adding to group!
			// The AI combat component crashes if it simulates before the group's
			// SCR_AIGroupUtilityComponent is fully initialized.
			AIControlComponent aiCtrl = AIControlComponent.Cast(aiEnt.FindComponent(AIControlComponent));
			if (!aiCtrl) { Print("[AutoSquad] LiveManual: no AIControlComponent on #" + i); continue; }

			// Add to SLAVE group FIRST (NOT master group!) — this triggers RPL broadcast
		// Set faction on each AI soldier to match master group faction
		FactionAffiliationComponent mFac = FactionAffiliationComponent.Cast(grp.FindComponent(FactionAffiliationComponent));
		FactionAffiliationComponent aiFac = FactionAffiliationComponent.Cast(aiEnt.FindComponent(FactionAffiliationComponent));
		if (mFac && aiFac)
		{
			Faction grpFaction = mFac.GetAffiliatedFaction();
			if (grpFaction)
			{
				aiFac.SetAffiliatedFaction(grpFaction);
			}
		}

			slaveGroup.AddAgentFromControlledEntity(aiEnt);

			// Activate AI AFTER group assignment — delay to let group components initialize
			GetGame().GetCallqueue().CallLater(aiCtrl.ActivateAI, 500, false);

			Print("[AutoSquad] LiveManual: AI #" + i + " spawned and added to SLAVE group at " + spawnPos);
		}

		// Set formation on the slave group
		AIFormationComponent formationComp = AIFormationComponent.Cast(slaveGroup.FindComponent(AIFormationComponent));
		if (formationComp)
		{
			formationComp.SetFormation("Column");
			Print("[AutoSquad] LiveManual: formation set to Column on slave group");
		}
		else
		{
			Print("[AutoSquad] LiveManual: WARNING - no AIFormationComponent on slave group!");
		}

		Print("[AutoSquad] LiveManual: Done, 5 AI spawned with formation");

		// Auto-follow: create a Follow waypoint at player position so squad follows by default
		Resource followRes = Resource.Load("{A0509D3C4DD4475E}Prefabs/AI/Waypoints/AIWaypoint_Follow.et");
		if (followRes && followRes.IsValid())
		{
			EntitySpawnParams wpParams = new EntitySpawnParams();
			wpParams.TransformMode = ETransformMode.WORLD;
			wpParams.Transform[3] = playerPos;
			AIWaypoint followWP = AIWaypoint.Cast(GetGame().SpawnEntityPrefab(followRes, GetGame().GetWorld(), wpParams));
			if (followWP)
			{
				slaveGroup.AddWaypoint(followWP);
				Print("[AutoSquad] Auto-follow: Follow waypoint created at " + playerPos);
			}
		}
	}

	//------------------------------------------------------------------------------------------------
	// F2.x: Move agents from master group to slave group + auto-follow
	// This is called after SpawnUnits() succeeds to fix MP group visibility
	static void MoveAgentsToSlaveGroup(int playerID)
	{
		SCR_AIGroup grp = s_PlayerGroup;
		if (!grp) { Print("[AutoSquad] MoveToSlave: no group"); return; }

		array<AIAgent> agents = {};
		int count = grp.GetAgents(agents);
		if (count == 0)
		{
			Print("[AutoSquad] MoveToSlave: no agents in master group, nothing to move");
			return;
		}

		// Ensure slave group exists
		SCR_AIGroup slaveGroup = EnsureSlaveGroup(grp);
		if (!slaveGroup)
		{
			Print("[AutoSquad] MoveToSlave: failed to create slave group");
			return;
		}

		Print("[AutoSquad] MoveToSlave: moving " + count + " agents from master to slave group");

		// Move each agent from master to slave group
		PlayerManager pm = GetGame().GetPlayerManager();
		IEntity playerEnt = null;
		if (pm)
			playerEnt = pm.GetPlayerControlledEntity(playerID);
		vector followPos = grp.GetOrigin();
		if (playerEnt)
			followPos = playerEnt.GetOrigin();

		int moved = 0;
		for (int i = 0; i < count; i++)
		{
			AIAgent agent = agents[i];
			if (!agent) continue;

			// Skip if already in slave group
			if (agent.GetParentGroup() == slaveGroup) continue;

			// Get the controlled entity — needed for AddAgentFromControlledEntity (RPL broadcast)
			IEntity aiEnt = agent.GetControlledEntity();
			if (!aiEnt) continue;

			// Remove from master group
			grp.RemoveAgent(agent);

			// Add to slave group using AddAgentFromControlledEntity (triggers RPL broadcast!)
			// This is the vanilla pattern from SCR_PlayerControllerGroupComponent.AddAIToSlaveGroup()
			slaveGroup.AddAgentFromControlledEntity(aiEnt);

			moved++;
		}

		Print("[AutoSquad] MoveToSlave: " + moved + " agents moved to slave group");

		// Set formation on slave group
		AIFormationComponent fc = AIFormationComponent.Cast(slaveGroup.FindComponent(AIFormationComponent));
		if (fc)
		{
			fc.SetFormation("Column");
			Print("[AutoSquad] MoveToSlave: formation set to Column");
		}

		// Auto-follow: create Follow waypoint at player position
		Resource followRes = Resource.Load("{A0509D3C4DD4475E}Prefabs/AI/Waypoints/AIWaypoint_Follow.et");
		if (followRes && followRes.IsValid())
		{
			EntitySpawnParams wpParams = new EntitySpawnParams();
			wpParams.TransformMode = ETransformMode.WORLD;
			wpParams.Transform[3] = followPos;
			AIWaypoint followWP = AIWaypoint.Cast(GetGame().SpawnEntityPrefab(followRes, GetGame().GetWorld(), wpParams));
			if (followWP)
			{
				slaveGroup.AddWaypoint(followWP);
				Print("[AutoSquad] MoveToSlave: auto-follow waypoint created at " + followPos);
			}
		}
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
	// F2.x: Ensure slave group exists for AI commanding (MP-critical!)
	// The vanilla commanding system expects AI in a SLAVE group linked to the player's MASTER group.
	// Without this, spawned AI cannot be commanded in multiplayer.
	static SCR_AIGroup EnsureSlaveGroup(SCR_AIGroup masterGroup)
	{
		if (!masterGroup) return null;

		// Check if slave group already exists
		SCR_AIGroup existingSlave = masterGroup.GetSlave();
		if (existingSlave)
		{
			Print("[AutoSquad] Slave group already exists: " + existingSlave);
			if (!existingSlave.IsAIActivated())
				existingSlave.ActivateAI();
			return existingSlave;
		}

		// Create slave group using the vanilla prefab
		SCR_CommandingManagerComponent commandingMgr = SCR_CommandingManagerComponent.GetInstance();
		if (!commandingMgr)
		{
			Print("[AutoSquad] EnsureSlaveGroup: no CommandingManagerComponent!");
			return null;
		}

		ResourceName slavePrefab = commandingMgr.GetGroupPrefab();
		if (slavePrefab.IsEmpty())
		{
			Print("[AutoSquad] EnsureSlaveGroup: no slave group prefab!");
			return null;
		}

		Resource res = Resource.Load(slavePrefab);
		if (!res || !res.IsValid())
		{
			Print("[AutoSquad] EnsureSlaveGroup: failed to load slave prefab!");
			return null;
		}

		IEntity slaveEntity = GetGame().SpawnEntityPrefab(res, GetGame().GetWorld());
		if (!slaveEntity)
		{
			Print("[AutoSquad] EnsureSlaveGroup: failed to spawn slave group entity!");
			return null;
		}

		SCR_AIGroup slaveGroup = SCR_AIGroup.Cast(slaveEntity);
		if (!slaveGroup)
		{
			Print("[AutoSquad] EnsureSlaveGroup: spawned entity is not SCR_AIGroup!");
			return null;
		}

		// Don't delete when empty (vanilla pattern)
		slaveGroup.SetDeleteWhenEmpty(false);
		slaveGroup.ActivateAI();

		// CRITICAL: Set slave group faction to match master group
		// Without this, AI soldiers may engage the player as hostile
		FactionAffiliationComponent masterFac = FactionAffiliationComponent.Cast(masterGroup.FindComponent(FactionAffiliationComponent));
		FactionAffiliationComponent slaveFac = FactionAffiliationComponent.Cast(slaveGroup.FindComponent(FactionAffiliationComponent));
		if (masterFac && slaveFac)
		{
			Faction masterFaction = masterFac.GetAffiliatedFaction();
			if (masterFaction)
			{
				slaveFac.SetAffiliatedFaction(masterFaction);
				Print("[AutoSquad] Slave group faction set to: " + masterFaction.GetFactionKey());
			}
		}
		else
		{
			Print("[AutoSquad] WARNING: could not set slave group faction - friendly fire risk!");
		}

		// Link slave to master via GroupsManager
		SCR_GroupsManagerComponent groupsMgr = SCR_GroupsManagerComponent.GetInstance();
		if (groupsMgr)
		{
			RplComponent masterRpl = RplComponent.Cast(masterGroup.FindComponent(RplComponent));
			RplComponent slaveRpl = RplComponent.Cast(slaveGroup.FindComponent(RplComponent));
			if (masterRpl && slaveRpl)
			{
				groupsMgr.RequestSetGroupSlave(masterRpl.Id(), slaveRpl.Id());
				Print("[AutoSquad] Slave group created and linked to master group");
			}
		}

		return slaveGroup;
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
	// F4: Mount nearest vehicle - put squad AI in driver + passenger seats
	static void MountNearestVehicle()
	{
		SCR_AIGroup grp = s_PlayerGroup;
		if (!grp)
		{
			Print("[AutoSquad] Mount: no group, trying dynamic lookup...");
			PlayerManager pm = GetGame().GetPlayerManager();
			if (!pm) { Print("[AutoSquad] Mount: no PlayerManager"); return; }
			for (int pid = 1; pid <= 32; pid++)
			{
				IEntity pEnt = pm.GetPlayerControlledEntity(pid);
				if (!pEnt) continue;
				AIControlComponent aiCtrl = AIControlComponent.Cast(pEnt.FindComponent(AIControlComponent));
				if (aiCtrl)
				{
					AIAgent pAgent = aiCtrl.GetControlAIAgent();
					if (pAgent)
					{
						AIGroup rawGrp = pAgent.GetParentGroup();
						if (rawGrp) { grp = SCR_AIGroup.Cast(rawGrp); s_PlayerGroup = grp; break; }
					}
				}
			}
			if (!grp) { Print("[AutoSquad] Mount: no group found"); return; }
		}

		// Get squad position
		vector squadPos = GetSquadCenterPosition(grp);
		Print("[AutoSquad] Mount: searching for vehicle near " + squadPos);

		// Search for vehicles in 60m radius using callback
		g_aQueriedEntities.Clear();
		GetGame().GetWorld().QueryEntitiesBySphere(squadPos, 60, QueryEntityCallback);

		IEntity nearestVehicle = null;
		float nearestDist = 9999;

		for (int e = 0; e < g_aQueriedEntities.Count(); e++)
		{
			IEntity ent = g_aQueriedEntities.Get(e);
			if (!ent) continue;

			// Check if it's a vehicle
			Vehicle vehicle = Vehicle.Cast(ent);
			if (!vehicle) continue;

			// Skip destroyed vehicles
			SCR_DamageManagerComponent dmgMgr = SCR_DamageManagerComponent.Cast(ent.FindComponent(SCR_DamageManagerComponent));
			if (dmgMgr && dmgMgr.IsDestroyed()) continue;

			// Check distance
			vector entPos = ent.GetOrigin();
			float dist = vector.Distance(squadPos, entPos);
			if (dist < nearestDist)
			{
				// Check if vehicle has free compartments
				SCR_BaseCompartmentManagerComponent compMgr = SCR_BaseCompartmentManagerComponent.Cast(
					ent.FindComponent(SCR_BaseCompartmentManagerComponent));
				if (compMgr)
				{
					nearestDist = dist;
					nearestVehicle = ent;
				}
			}
		}

		if (!nearestVehicle)
		{
			Print("[AutoSquad] Mount: no vehicle found within 60m");
			return;
		}

		Print("[AutoSquad] Mount: found vehicle " + nearestVehicle + " at " + nearestDist + "m");

		// Get AI agents from slave group
		SCR_AIGroup slaveGroup = grp.GetSlave();
		if (!slaveGroup) { Print("[AutoSquad] Mount: no slave group"); return; }

		array<AIAgent> agents = {};
		slaveGroup.GetAgents(agents);

		if (agents.Count() == 0)
		{
			Print("[AutoSquad] Mount: no AI agents in slave group");
			return;
		}

		// First AI = driver (PILOT), rest = CARGO (passengers)
		int mounted = 0;
		for (int i = 0; i < agents.Count(); i++)
		{
			IEntity aiEnt = agents[i].GetControlledEntity();
			if (!aiEnt) continue;

			SCR_CompartmentAccessComponent compAccess = SCR_CompartmentAccessComponent.Cast(
				aiEnt.FindComponent(SCR_CompartmentAccessComponent));
			if (!compAccess) continue;

			// Skip if already in vehicle
			if (compAccess.IsInCompartment()) continue;

			bool success = false;
			if (i == 0)
			{
				// Driver seat
				success = compAccess.MoveInVehicle(nearestVehicle, ECompartmentType.PILOT);
				Print("[AutoSquad] Mount: AI #" + i + " -> PILOT seat: " + success);
			}
			else
			{
				// Passenger seat
				success = compAccess.MoveInVehicle(nearestVehicle, ECompartmentType.CARGO);
				Print("[AutoSquad] Mount: AI #" + i + " -> CARGO seat: " + success);
			}

			if (success) mounted++;
		}

		Print("[AutoSquad] Mount: " + mounted + " AI in vehicle");
	}

	// F4: Dismount - get all AI out of vehicle
	static void DismountVehicle()
	{
		SCR_AIGroup grp = s_PlayerGroup;
		if (!grp) { Print("[AutoSquad] Dismount: no group"); return; }

		SCR_AIGroup slaveGroup = grp.GetSlave();
		if (!slaveGroup) { Print("[AutoSquad] Dismount: no slave group"); return; }

		array<AIAgent> agents = {};
		slaveGroup.GetAgents(agents);

		int dismounted = 0;
		for (int i = 0; i < agents.Count(); i++)
		{
			IEntity aiEnt = agents[i].GetControlledEntity();
			if (!aiEnt) continue;

			SCR_CompartmentAccessComponent compAccess = SCR_CompartmentAccessComponent.Cast(
				aiEnt.FindComponent(SCR_CompartmentAccessComponent));
			if (!compAccess) continue;

			if (compAccess.IsInCompartment())
			{
				compAccess.AskOwnerToGetOutFromVehicle(0, 0, 0, false, false);
				dismounted++;
				Print("[AutoSquad] Dismount: AI #" + i + " out of vehicle");
			}
		}

		Print("[AutoSquad] Dismount: " + dismounted + " AI out of vehicle");
	}

	// Helper: get center position of squad (average of all AI positions)
	static vector GetSquadCenterPosition(SCR_AIGroup grp)
	{
		vector center = "0 0 0";
		int count = 0;

		// Try slave group agents
		SCR_AIGroup slaveGroup = grp.GetSlave();
		if (slaveGroup)
		{
			array<AIAgent> agents = {};
			slaveGroup.GetAgents(agents);
			foreach (AIAgent agent : agents)
			{
				IEntity ent = agent.GetControlledEntity();
				if (ent) { center += ent.GetOrigin(); count++; }
			}
		}

		// Try master group agents
		array<AIAgent> masterAgents = {};
		grp.GetAgents(masterAgents);
		foreach (AIAgent agent : masterAgents)
		{
			IEntity ent = agent.GetControlledEntity();
			if (ent) { center += ent.GetOrigin(); count++; }
		}

		// Try player position
		PlayerManager pm = GetGame().GetPlayerManager();
		if (count == 0 && pm)
		{
			for (int pid = 1; pid <= 32; pid++)
			{
				IEntity pEnt = pm.GetPlayerControlledEntity(pid);
				if (pEnt) { center = pEnt.GetOrigin(); count = 1; break; }
			}
		}

		if (count > 0) center = center / count;
		return center;
	}

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
	protected int m_iAutoSquadRetries = 0;

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
		m_iAutoSquadRetries = 0;
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

			// --- RESPAWN DETECTION: re-link existing slave group if AI still alive ---
			SCR_AIGroup existingSlave = scrGroup.GetSlave();
			if (existingSlave)
			{
				array<AIAgent> slaveAgents = {};
				existingSlave.GetAgents(slaveAgents);
				if (slaveAgents.Count() > 0)
				{
					Print("[AutoSquad] RESPAWN: slave group has " + slaveAgents.Count() + " AI agents — re-linking, skipping new spawn");

					// Re-ensure slave AI is active
					if (!existingSlave.IsAIActivated())
						existingSlave.ActivateAI();

					// Set formation on slave group
					AIFormationComponent fc = AIFormationComponent.Cast(existingSlave.FindComponent(AIFormationComponent));
					if (fc)
					{
						fc.SetFormation("Column");
						Print("[AutoSquad] RESPAWN: formation re-set to Column");
					}

					// Create fresh Follow waypoint at player's new position
					Resource followRes = Resource.Load("{A0509D3C4DD4475E}Prefabs/AI/Waypoints/AIWaypoint_Follow.et");
					if (followRes && followRes.IsValid())
					{
						EntitySpawnParams wpParams = new EntitySpawnParams();
						wpParams.TransformMode = ETransformMode.WORLD;
						wpParams.Transform[3] = playerEntity.GetOrigin();
						AIWaypoint followWP = AIWaypoint.Cast(GetGame().SpawnEntityPrefab(followRes, GetGame().GetWorld(), wpParams));
						if (followWP)
						{
							existingSlave.AddWaypoint(followWP);
							Print("[AutoSquad] RESPAWN: new follow waypoint at player position " + playerEntity.GetOrigin());
						}
					}

					// Store group reference for LLMBridge
					SCR_AIWorld.SetPlayerGroup(scrGroup);
					Print("[AutoSquad] RESPAWN: squad re-linked successfully, no new AI spawned");
					return;
				}
				else
				{
					Print("[AutoSquad] RESPAWN: slave group exists but has 0 agents — will spawn new squad");
				}
			}

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

			// Check result after 10s and move AI to slave group
			GetGame().GetCallqueue().CallLater(SCR_AIWorld.LiveSpawnCheck, 10000, false, playerID);
			GetGame().GetCallqueue().CallLater(SCR_AIWorld.MoveAgentsToSlaveGroup, 12000, false, playerID);

			// F2: Store group reference for LLMBridge waypoint execution
			SCR_AIWorld.SetPlayerGroup(scrGroup);

			Print("[AutoSquad] SUCCESS: Auto-squad complete for player " + playerID);
		}
		else
		{
			m_iAutoSquadRetries++;
		if (m_iAutoSquadRetries <= 18)
		{
			Print("[AutoSquad] No group yet, retry " + m_iAutoSquadRetries + "/18 in 10s (player may not have joined group)");
			GetGame().GetCallqueue().CallLater(DeferredAutoSquad, 10000, false, playerID);
		}
		else
		{
			Print("[AutoSquad] No group found after 18 retries (3min). Use /orders cmd=spawn to manually spawn later.");
		}
		}
	}
};
