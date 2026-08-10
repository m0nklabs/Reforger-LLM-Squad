// StavkaController.c - F3.1: OPFOR strategic AI
// Polls bridge for strategic orders, spawns OPFOR groups, assigns waypoints
//
// USSR soldier prefab confirmed from vanilla SDK:
//   {DCB41B3746FDD1BE}Prefabs/Characters/OPFOR/USSR_Army/Character_USSR_Rifleman.et
// Source: SCR_DebugEditorComponent.c

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

	float m_fTimer;
	static const float STAVKA_INTERVAL = 60.0; // 60s between strategic cycles

	string m_sBridgeURL;

	//------------------------------------------------------------------------------------------------
	void StavkaController(string bridgeURL)
	{
		m_sBridgeURL = bridgeURL;
		m_aCallbacks = new array<ref StavkaRestCallback>;
		m_fTimer = 0;
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

		StavkaRestCallback cb = new StavkaRestCallback(this);
		m_aCallbacks.Insert(cb);
		while (m_aCallbacks.Count() > 10)
			m_aCallbacks.RemoveOrdered(0);

		m_Rest.GET(cb, "/stavka");
		Print("[Stavka] Polling bridge for strategic orders");
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
		// Get BLUFOR position (player group)
		SCR_AIGroup bluforGroup = SCR_AIWorld.GetPlayerGroup();
		vector bluforPos = "0 0 0";
		if (bluforGroup)
			bluforPos = bluforGroup.GetOrigin();
		else
		{
			PlayerManager pm = GetGame().GetPlayerManager();
			if (pm)
			{
				IEntity p = pm.GetPlayerControlledEntity(1);
				if (p) bluforPos = p.GetOrigin();
			}
		}

		vector spawnPos = bluforPos + offset;
		spawnPos[1] = bluforPos[1];

		Print("[Stavka] Spawning " + count + " OPFOR at offset " + offset + " from BLUFOR (spawn=" + spawnPos + ")");

		// USSR Rifleman — confirmed prefab from SCR_DebugEditorComponent.c
		ResourceName prefabPath = "{DCB41B3746FDD1BE}Prefabs/Characters/OPFOR/USSR_Army/Character_USSR_Rifleman.et";
		Resource res = Resource.Load(prefabPath);
		if (!res || !res.IsValid())
		{
			Print("[Stavka] ERROR: USSR Rifleman prefab failed to load!");
			return;
		}

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
				SCR_FactionManager fm = SCR_FactionManager.Cast(GetGame().GetFactionManager());
				if (fm)
				{
					Faction ussr = fm.GetFactionByKey("USSR");
					if (ussr)
						facComp.SetAffiliatedFaction(ussr);
				}
			}

			// Activate AI (delayed to prevent combat component crash — AGENTS.md rule 21)
			AIControlComponent aiCtrl = AIControlComponent.Cast(aiEnt.FindComponent(AIControlComponent));
			if (aiCtrl)
				GetGame().GetCallqueue().CallLater(aiCtrl.ActivateAI, 500, false);

			Print("[Stavka] OPFOR soldier #" + i + " spawned at " + sp);
		}

		Print("[Stavka] OPFOR group of " + count + " spawned near " + spawnPos);
	}
}
