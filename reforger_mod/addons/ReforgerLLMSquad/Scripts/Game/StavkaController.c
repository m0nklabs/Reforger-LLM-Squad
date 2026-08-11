// StavkaController.c - F3.1: OPFOR strategic AI
// Polls bridge for strategic orders, spawns OPFOR groups, assigns waypoints
//
// USSR soldier prefab confirmed from vanilla SDK:
//   {DCB41B3746FDD1BE}Prefabs/Characters/OPFOR/USSR_Army/Character_USSR_Rifleman.et
// Source: SCR_DebugEditorComponent.c

// F3.4: Global singleton for cross-class access (LLMBridge reads OPFOR positions)
StavkaController g_StavkaInstance;

//------------------------------------------------------------------------------------------------
// Simple REST callback for Stavka (avoids cross-file dependency on LLMBridgeRestCallback)
class StavkaRestCallback : RestCallback
{
	StavkaController m_pOwner;

	void StavkaRestCallback(StavkaController pOwner)
	{
		m_pOwner = pOwner;
		SetOnSuccess(SuccessHandler);
	}

	void SuccessHandler(RestCallback cb = null)
	{
		// Skipped - OnSuccess override provides actual response data
	}

	override void OnSuccess(string data, int dataSize)
	{
		if (m_pOwner)
			m_pOwner.OnStavkaResponse(data);
	}

	override void OnError(int errorCode)
	{
		if (m_pOwner)
			Print("[Stavka] REST error: " + errorCode);
	}
}

//------------------------------------------------------------------------------------------------
class StavkaController
{
	RestContext m_Rest;
	ref array<ref StavkaRestCallback> m_aCallbacks;

	// F3.2: Track spawned OPFOR groups for cap enforcement
	// NOTE: SCR_AIGroup is engine class — no 'ref' on element type, but array itself needs 'ref'
	ref array<SCR_AIGroup> m_aOPFORGroups;

	float m_fTimer;
	static const float STAVKA_INTERVAL = 60.0; // 60s between strategic cycles
	static const float CASUALTY_CHECK_INTERVAL = 10.0; // 10s between casualty checks

	// F3.3: Track last OPFOR count for casualty detection
	int m_iLastOPFORCount;
	float m_fCasualtyTimer;

	string m_sBridgeURL;

	//------------------------------------------------------------------------------------------------
	void StavkaController(string bridgeURL)
	{
		m_sBridgeURL = bridgeURL;
		m_aCallbacks = new array<ref StavkaRestCallback>;
		m_aOPFORGroups = new array<SCR_AIGroup>;
		m_fTimer = 0;
		m_fCasualtyTimer = 0;
		m_iLastOPFORCount = 0;
		g_StavkaInstance = this;
		Print("[Stavka] Controller initialized (bridge=" + bridgeURL + ")");
	}

	//------------------------------------------------------------------------------------------------
	void Update(float timeslice)
	{
		m_fTimer += timeslice;
		if (m_fTimer >= STAVKA_INTERVAL)
		{
			m_fTimer = 0;
			PollStavka();
			return;
		}

		// F3.3: Casualty check - if OPFOR count drops, trigger immediate poll
		m_fCasualtyTimer += timeslice;
		if (m_fCasualtyTimer >= CASUALTY_CHECK_INTERVAL)
		{
			m_fCasualtyTimer = 0;
			int currentOPFOR = CountAliveOPFOR();
			if (m_iLastOPFORCount > 0 && currentOPFOR < m_iLastOPFORCount)
			{
				int casualties = m_iLastOPFORCount - currentOPFOR;
				Print("[Stavka] CASUALTY REPORT: " + casualties + " OPFOR lost (" + currentOPFOR + "/" + m_iLastOPFORCount + " remaining) — triggering immediate strategic poll");
				m_fTimer = STAVKA_INTERVAL; // Force immediate poll
			}
		}
	}

	//------------------------------------------------------------------------------------------------
	void PollStavka()
	{
		if (!m_Rest)
		{
			m_Rest = GetGame().GetRestApi().GetContext(m_sBridgeURL);
			Print("[Stavka] REST context created");
		}

		// F3.3: Send current OPFOR count to bridge for adaptive strategy
		int opforCount = CountAliveOPFOR();
		m_iLastOPFORCount = opforCount;

		StavkaRestCallback cb = new StavkaRestCallback(this);
		m_aCallbacks.Insert(cb);
		while (m_aCallbacks.Count() > 10)
			m_aCallbacks.RemoveOrdered(0);

		m_Rest.GET(cb, "/stavka?opfor=" + opforCount);
		Print("[Stavka] Polling bridge for strategic orders (OPFOR=" + opforCount + ")");
	}

	//------------------------------------------------------------------------------------------------
	void OnStavkaResponse(string sData)
	{
		if (!sData || sData.IsEmpty())
		{
			Print("[Stavka] Empty response");
			return;
		}

		Print("[Stavka] Response: " + sData);

		// Parse JSON: {"orders": [{"action": "spawn_and_move", "count": 3, "offset": [200, -100]}]}
		int ordersIdx = sData.IndexOf("\"orders\"");
		if (ordersIdx < 0)
		{
			Print("[Stavka] No orders field found");
			return;
		}

		int arrStart = sData.IndexOfFrom(ordersIdx, "[");
		if (arrStart < 0) return;

		int scanPos = arrStart + 1;
		int orderCount = 0;

		while (scanPos < sData.Length())
		{
			int objStart = sData.IndexOfFrom(scanPos, "{");
			if (objStart < 0) break;
			int objEnd = sData.IndexOfFrom(objStart, "}");
			if (objEnd < 0) break;

			string orderJson = sData.Substring(objStart, objEnd - objStart + 1);

			// Parse action
			string action = "";
			int actIdx = orderJson.IndexOf("\"action\"");
			if (actIdx >= 0)
			{
				int colon = orderJson.IndexOfFrom(actIdx, ":");
				int qStart = orderJson.IndexOfFrom(colon, "\"");
				int qEnd = orderJson.IndexOfFrom(qStart + 1, "\"");
				if (qStart >= 0 && qEnd >= 0)
					action = orderJson.Substring(qStart + 1, qEnd - qStart - 1);
			}

			// Parse count
			int count = 3;
			int countIdx = orderJson.IndexOf("\"count\"");
			if (countIdx >= 0)
			{
				int colon = orderJson.IndexOfFrom(countIdx, ":");
				int numStart = colon + 1;
				while (numStart < orderJson.Length() && (orderJson.Get(numStart) == " " || orderJson.Get(numStart) == "\t"))
					numStart++;
				string numStr = "";
				int ns = numStart;
				while (ns < orderJson.Length())
				{
					string ch = orderJson.Get(ns);
					if (ch >= "0" && ch <= "9")
					{
						numStr += ch;
						ns++;
					}
					else break;
				}
				if (!numStr.IsEmpty()) count = numStr.ToInt();
			}

			// Parse offset [dx, dz]
			vector offset = "0 0 0";
			bool hasOffset = false;
			int offIdx = orderJson.IndexOf("\"offset\"");
			if (offIdx >= 0)
			{
				int colon = orderJson.IndexOfFrom(offIdx, ":");
				int aStart = orderJson.IndexOfFrom(colon, "[");
				int aEnd = orderJson.IndexOfFrom(aStart, "]");
				if (aStart >= 0 && aEnd >= 0)
				{
					string arrStr = orderJson.Substring(aStart + 1, aEnd - aStart - 1);
					float nums[2];
					int numCount = 0;
					int sc = 0;
					while (sc < arrStr.Length() && numCount < 2)
					{
						int comma = arrStr.IndexOfFrom(sc, ",");
						if (comma < 0) comma = arrStr.Length();
						string s = arrStr.Substring(sc, comma - sc);
						s.Replace(" ", "");
						if (!s.IsEmpty()) { nums[numCount] = s.ToFloat(); numCount++; }
						sc = comma + 1;
					}
					if (numCount >= 2) { offset[0] = nums[0]; offset[2] = nums[1]; hasOffset = true; }
				}
			}

			Print("[Stavka] Order: action=" + action + " count=" + count + " offset=" + offset);

			if (action == "spawn_and_move" && hasOffset)
			{
				SpawnOPFORGroup(count, offset);
				orderCount++;
			}
			else if (action == "hold")
			{
				Print("[Stavka] Hold order — maintaining current forces");
			}

			scanPos = objEnd + 1;
		}

		if (orderCount > 0)
			Print("[Stavka] Executed " + orderCount + " strategic orders");
		else
			Print("[Stavka] No actionable orders this cycle");
	}

	//------------------------------------------------------------------------------------------------
	void SpawnOPFORGroup(int count, vector offset)
	{
		// RPL authority: entity spawning only allowed server-side
		if (!Replication.IsServer())
		{
			Print("[Stavka] SpawnOPFORGroup: skipped (not server authority)");
			return;
		}

		// Get BLUFOR position via robust lookup (same as LLMBridge)
		vector bluforPos = SCR_AIWorld.GetBLUFORPosition();

		if (bluforPos == "0 0 0")
		{
			Print("[Stavka] WARNING: BLUFOR position unknown, cannot spawn OPFOR");
			return;
		}

		// Safety: clamp offset to reasonable range (LLM sometimes returns absolute coords)
		float maxOffset = 500.0;
		if (Math.AbsFloat(offset[0]) > maxOffset || Math.AbsFloat(offset[2]) > maxOffset)
		{
			Print("[Stavka] WARNING: offset " + offset + " exceeds " + maxOffset + "m, likely absolute coords - clamping");
			if (offset[0] > maxOffset) offset[0] = maxOffset;
			if (offset[0] < -maxOffset) offset[0] = -maxOffset;
			if (offset[2] > maxOffset) offset[2] = maxOffset;
			if (offset[2] < -maxOffset) offset[2] = -maxOffset;
		}


		// Enforce minimum spawn distance: OPFOR must not spawn within 100m of BLUFOR
		float offsetDist = Math.Sqrt(offset[0] * offset[0] + offset[2] * offset[2]);
		if (offsetDist < 100.0)
		{
			Print("[Stavka] WARNING: offset " + offset + " too close (" + offsetDist + "m), pushing OPFOR to 150m");
			if (offsetDist < 1.0)
			{
				float angle = 1.5708; // fixed angle (NE)
				offset[0] = Math.Cos(angle) * 150.0;
				offset[2] = Math.Sin(angle) * 150.0;
			}
			else
			{
				float scale = 150.0 / offsetDist;
				offset[0] = offset[0] * scale;
				offset[2] = offset[2] * scale;
			}
		}
		vector spawnPos = bluforPos + offset;
		spawnPos[1] = bluforPos[1];

		Print("[Stavka] BLUFOR at " + bluforPos + ", offset " + offset + ", spawn at " + spawnPos);

		// F3.2: Limit total OPFOR to prevent unbounded spawning
		int totalOPFOR = CountAliveOPFOR();
		int MAX_OPFOR = 10;
		if (totalOPFOR >= MAX_OPFOR)
		{
			Print("[Stavka] OPFOR cap reached (" + totalOPFOR + "/" + MAX_OPFOR + "), skipping spawn");
			return;
		}
		if (totalOPFOR + count > MAX_OPFOR)
		{
			count = MAX_OPFOR - totalOPFOR;
			Print("[Stavka] Capping spawn to " + count + " (total cap=" + MAX_OPFOR + ")");
		}

		// USSR Rifleman — confirmed prefab from SCR_DebugEditorComponent.c
		ResourceName prefabPath = "{DCB41B3746FDD1BE}Prefabs/Characters/OPFOR/USSR_Army/Character_USSR_Rifleman.et";
		Resource res = Resource.Load(prefabPath);
		if (!res || !res.IsValid())
		{
			Print("[Stavka] ERROR: USSR Rifleman prefab failed to load!");
			return;
		}

		// Look up USSR faction (needed for both group and per-soldier assignment)
		Faction ussrFaction = null;
		SCR_FactionManager fm = SCR_FactionManager.Cast(GetGame().GetFactionManager());
		if (fm)
			ussrFaction = fm.GetFactionByKey("USSR");

		// Create an AI group for the OPFOR soldiers
		// Use the slave group prefab from SCR_CommandingManagerComponent
		SCR_CommandingManagerComponent commandingMgr = SCR_CommandingManagerComponent.GetInstance();
		ResourceName groupPrefab = "{04D3B38E23F51754}Prefabs/AI/Groups/Slave_Group.et";
		if (commandingMgr)
		{
			ResourceName mgrPrefab = commandingMgr.GetGroupPrefab();
			if (!mgrPrefab.IsEmpty())
				groupPrefab = mgrPrefab;
		}

		Resource groupRes = Resource.Load(groupPrefab);
		SCR_AIGroup opforGroup = null;

		if (groupRes && groupRes.IsValid())
		{
			EntitySpawnParams groupParams = new EntitySpawnParams();
			groupParams.TransformMode = ETransformMode.WORLD;
			groupParams.Transform[3] = spawnPos;

			IEntity groupEntity = GetGame().SpawnEntityPrefab(groupRes, GetGame().GetWorld(), groupParams);
			if (groupEntity)
			{
				opforGroup = SCR_AIGroup.Cast(groupEntity);
				if (opforGroup)
				{
					opforGroup.SetDeleteWhenEmpty(false);
					opforGroup.SetMaxMembers(count + 1);
					opforGroup.ActivateAI();

					Print("[Stavka] OPFOR group created: " + opforGroup);
				}
			}
		}

		if (!opforGroup)
		{
			Print("[Stavka] WARNING: Failed to create group, spawning without group");
		}

		// Spawn each soldier and add to group
		array<IEntity> spawnedEntities = {};
		for (int i = 0; i < count; i++)
		{
			vector sp = spawnPos;
			sp[0] = spawnPos[0] + i * 2;
			sp[2] = spawnPos[2] + i * 2;

			EntitySpawnParams params = new EntitySpawnParams();
			params.TransformMode = ETransformMode.WORLD;
			params.Transform[3] = sp;

			IEntity aiEnt = GetGame().SpawnEntityPrefabEx(prefabPath, true, GetGame().GetWorld(), params);
			if (!aiEnt)
			{
				Print("[Stavka] Failed to spawn OPFOR #" + i);
				continue;
			}

			// Set faction to USSR
			FactionAffiliationComponent facComp = FactionAffiliationComponent.Cast(aiEnt.FindComponent(FactionAffiliationComponent));
			if (facComp)
			{
				if (ussrFaction)
					facComp.SetAffiliatedFaction(ussrFaction);
			}

			// Add to group BEFORE activating AI (AGENTS.md rule 21: prevents combat component crash)
			if (opforGroup)
				opforGroup.AddAgentFromControlledEntity(aiEnt);

			// Activate AI after delay (let group components initialize)
			AIControlComponent aiCtrl = AIControlComponent.Cast(aiEnt.FindComponent(AIControlComponent));
			if (aiCtrl)
				GetGame().GetCallqueue().CallLater(aiCtrl.ActivateAI, 500, false);

			spawnedEntities.Insert(aiEnt);
			Print("[Stavka] OPFOR soldier #" + i + " spawned at " + sp);
		}

		// Set formation on the OPFOR group
		if (opforGroup)
		{
			AIFormationComponent fc = AIFormationComponent.Cast(opforGroup.FindComponent(AIFormationComponent));
			if (fc)
			{
				fc.SetFormation("Wedge");
				Print("[Stavka] OPFOR formation: Wedge");
			}

			// F3.2: Create Move waypoint toward BLUFOR position
			// This makes OPFOR advance toward the player
			Resource moveRes = Resource.Load("{750A8D1695BD6998}Prefabs/AI/Waypoints/AIWaypoint_Move.et");
			if (moveRes && moveRes.IsValid())
			{
				EntitySpawnParams wpParams = new EntitySpawnParams();
				wpParams.TransformMode = ETransformMode.WORLD;
				wpParams.Transform[3] = bluforPos;

				AIWaypoint moveWP = AIWaypoint.Cast(GetGame().SpawnEntityPrefab(moveRes, GetGame().GetWorld(), wpParams));
				if (moveWP)
				{
					opforGroup.AddWaypoint(moveWP);
					Print("[Stavka] Move waypoint created at BLUFOR position " + bluforPos);
				}
			}

			m_aOPFORGroups.Insert(opforGroup);
		}

		Print("[Stavka] OPFOR group of " + spawnedEntities.Count() + " spawned with Move waypoint toward BLUFOR");
	}

	//------------------------------------------------------------------------------------------------
	// F3.2: Count alive OPFOR soldiers across all spawned groups
	int CountAliveOPFOR()
	{
		int alive = 0;
		for (int i = m_aOPFORGroups.Count() - 1; i >= 0; i--)
		{
			SCR_AIGroup grp = m_aOPFORGroups[i];
			if (!grp)
			{
				m_aOPFORGroups.RemoveOrdered(i);
				continue;
			}
			array<AIAgent> agents = {};
			grp.GetAgents(agents);
			alive += agents.Count();
		}
		return alive;
	}

	//------------------------------------------------------------------------------------------------
	// F3.4: Get all OPFOR agent positions for enemy detection
	// Returns array of vector positions of alive OPFOR soldiers
	array<vector> GetEnemyPositions()
	{
		array<vector> positions = {};
		for (int i = 0; i < m_aOPFORGroups.Count(); i++)
		{
			SCR_AIGroup grp = m_aOPFORGroups[i];
			if (!grp) continue;
			array<AIAgent> agents = {};
			grp.GetAgents(agents);
			for (int j = 0; j < agents.Count(); j++)
			{
				IEntity ent = agents[j].GetControlledEntity();
				if (ent) positions.Insert(ent.GetOrigin());
			}
		}
		return positions;
	}
}
