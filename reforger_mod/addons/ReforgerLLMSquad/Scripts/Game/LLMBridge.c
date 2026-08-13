// LLMBridge.c - LLM Squad Control Bridge for Arma Reforger
// Phase 1: REST bridge + AI squad control
// Phase 2: Waypoint execution + LIVE orders (debug without restart)

//------------------------------------------------------------------------------------------------
class LLMSquadMember
{
	string m_sName;
	bool m_bActive;
	string m_sCurrentOrder;
	vector m_vPosition;
	string m_sSITREP;

	void LLMSquadMember(string sName)
	{
		m_sName = sName;
		m_bActive = true;
		m_sCurrentOrder = "HOLD";
		m_vPosition = "0 0 0";
		m_sSITREP = "";
	}
}

//------------------------------------------------------------------------------------------------
class LLMWaypoint
{
	string m_sID;
	vector m_vPosition;
	string m_sType;
	bool m_bExecuted;
	float m_fSpawnTime;
	bool m_bUserOrder;   // true = placed by CO via /orders (dashboard/voice) — LLM HOLD must NOT clear these

	void LLMWaypoint(string sID, vector vPos, string sType)
	{
		m_sID = sID;
		m_vPosition = vPos;
		m_sType = sType;
		m_bExecuted = false;
		m_fSpawnTime = 0.0;
		m_bUserOrder = false;
	}
}

//------------------------------------------------------------------------------------------------
class LLMBridgeRestCallback : RestCallback
{
	LLMBridge m_pOwner;
	string m_sEndpoint;

	void LLMBridgeRestCallback(LLMBridge pOwner, string sEndpoint)
	{
		m_pOwner = pOwner;
		m_sEndpoint = sEndpoint;
		SetOnSuccess(SuccessHandler);
		SetOnError(ErrorHandler);
	}

	void SuccessHandler(RestCallback cb = null)
	{
		// Skipped - OnSuccess override provides actual response data
	}

	void ErrorHandler(RestCallback cb = null)
	{
		if (m_pOwner)
			m_pOwner.OnRestError(m_sEndpoint, 0);
	}

	override void OnSuccess(string data, int dataSize)
	{
		if (m_pOwner)
			m_pOwner.OnRestSuccess(m_sEndpoint, data);
	}

	override void OnError(int errorCode)
	{
		if (m_pOwner)
			m_pOwner.OnRestError(m_sEndpoint, errorCode);
	}
}

//------------------------------------------------------------------------------------------------
class LLMBridge
{
	// Config
	string m_sPythonBridgeURL;
	string m_sLLMModel;
	float m_fSITREPInterval;

	// Squad
	ref array<ref LLMSquadMember> m_aSquadMembers;

	// State
	bool m_bLLMReady;
	bool m_bPassiveMode;

	// REST
	RestContext m_Rest;
	ref array<ref LLMBridgeRestCallback> m_aActiveCallbacks;

	// Waypoints
	ref array<ref LLMWaypoint> m_aWaypoints;

	// Timers
	float m_fTime;
	float m_fSITREPTimer;
	float m_fStatusTimer;
	float m_fHealthCheckTimer;
	float m_fOrdersTimer;
	float m_fThoughtTimer;    // F2.7: AI brain thoughts
	float m_fThoughtCooldown;    // Minimum time between thought polls
	int m_iCurrentEnemyCount;      // F2.7+: Current enemy count
	int m_iLastEnemyCount;         // Previous enemy count (change detection)
	string m_sCurrentLLMAction;    // Current LLM action
	string m_sLastLLMAction;       // Previous LLM action
	int m_iCurrentSquadCount;       // Current squad count
	int m_iLastSquadCount;          // Previous squad count
	string m_sCurrentLeaderEvent;  // Current leader state
	string m_sLastLeaderEvent;      // Previous leader state
	string m_sLastAction;
	string m_sLastLeaderState; // F6: track leader state for change detection

	// Waypoint prefabs
	static const string WP_MOVE = "{750A8D1695BD6998}Prefabs/AI/Waypoints/AIWaypoint_Move.et";
	static const string WP_ATTACK = "{1B0E3436C30FA211}Prefabs/AI/Waypoints/AIWaypoint_Attack.et";
	static const string WP_DEFEND = "{93291E72AC23930F}Prefabs/AI/Waypoints/AIWaypoint_Defend.et";
	static const string WP_FOLLOW = "{A0509D3C4DD4475E}Prefabs/AI/Waypoints/AIWaypoint_Follow.et";

	//------------------------------------------------------------------------------------------------
	void LLMBridge()
	{
		m_sPythonBridgeURL = "http://127.0.0.1:5001";
		m_sLLMModel = "llama3";
		m_fSITREPInterval = 30.0; // 30s — slow LLM needs time, avoid bridge overload
		m_bLLMReady = false;
		m_bPassiveMode = false;
		m_fTime = 0;
		m_fSITREPTimer = 0;
		m_fStatusTimer = 0;
		m_fHealthCheckTimer = 0;
		m_fOrdersTimer = 0;
		m_fThoughtTimer = 0;
		m_iLastEnemyCount = 0;
		m_iCurrentEnemyCount = 0;
		m_iLastSquadCount = 0;
		m_iCurrentSquadCount = 0;

		m_aSquadMembers = new array<ref LLMSquadMember>;
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_1"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_2"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_3"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_4"));

		m_aWaypoints = new array<ref LLMWaypoint>;
		m_aActiveCallbacks = new array<ref LLMBridgeRestCallback>;

		Print("[LLMBridge] Initialized (bridge URL: " + m_sPythonBridgeURL + ")");
	}

	protected string BoolStr(bool b)
	{
		if (b) return "true";
		return "false";
	}

	protected LLMBridgeRestCallback CreateCallback(string sEndpoint)
	{
		LLMBridgeRestCallback cb = new LLMBridgeRestCallback(this, sEndpoint);
		m_aActiveCallbacks.Insert(cb);
		while (m_aActiveCallbacks.Count() > 20)
			m_aActiveCallbacks.RemoveOrdered(0);
		return cb;
	}

	protected void EnsureRest()
	{
		if (!m_Rest)
		{
			m_Rest = GetGame().GetRestApi().GetContext(m_sPythonBridgeURL);
			Print("[LLMBridge] REST context created");
		}
	}

	protected string UrlEncode(string s)
	{
		string r = "";
		for (int i = 0; i < s.Length(); i++)
		{
			string ch = s.Get(i);
			if (ch == " ") r += "%20";
			else if (ch == "\"") r += "%22";
			else if (ch == "{") r += "%7B";
			else if (ch == "}") r += "%7D";
			else if (ch == "[") r += "%5B";
			else if (ch == "]") r += "%5D";
			else if (ch == ":") r += "%3A";
			else if (ch == ",") r += "%2C";
			else r += ch;
		}
		return r;
	}

	void Activate()
	{
		Print("[LLMBridge] Activated");
		EnsureRest();
		CheckLLMHealth();
	}

	void Update(float timeslice)
	{
		m_fTime += timeslice;

		m_fSITREPTimer += timeslice;
		// NOTE: "last" tracking vars are shifted ONLY when a new SITREP is sent.
		// Shifting every frame would overwrite the previous value before the async
		// REST callback arrives (which updates "current"), so change detection
		// (contact/clear/casualty/order_change) would never fire.
		if (m_fSITREPTimer >= m_fSITREPInterval)
		{
			m_fSITREPTimer = 0;
			m_iLastEnemyCount = m_iCurrentEnemyCount;
			m_sLastLLMAction = m_sCurrentLLMAction;
			m_iLastSquadCount = m_iCurrentSquadCount;
			SendSITREP();
		}

		m_fStatusTimer += timeslice;
		if (m_fStatusTimer >= 5.0)
		{
			m_fStatusTimer = 0;
			UpdateStatus();
		}

		m_fOrdersTimer += timeslice;
		if (m_fOrdersTimer >= 2.0)
		{
			m_fOrdersTimer = 0;
			PollOrders();
		}

		// F2.7+: Event-driven AI thoughts (replaces 30s timer)
		// Thoughts triggered by events, not a schedule
		if (m_bLLMReady)
		{
			m_fThoughtTimer += timeslice;
			m_fThoughtCooldown += timeslice;

			// Check for events that should trigger thoughts
			string thoughtEvent = "";

			// Event: enemy contact appeared
			if (m_iLastEnemyCount == 0 && m_iCurrentEnemyCount > 0)
				thoughtEvent = "contact";

			// Event: enemies eliminated
			else if (m_iLastEnemyCount > 0 && m_iCurrentEnemyCount == 0)
				thoughtEvent = "clear";

			// Event: LLM order changed
			else if (!m_sLastLLMAction.IsEmpty() && m_sLastLLMAction != m_sCurrentLLMAction)
				thoughtEvent = "order_change";

			// Event: squad member lost
			else if (m_iLastSquadCount > m_iCurrentSquadCount)
				thoughtEvent = "casualty";

			// F6/F8: Event: leader state changed (downed/recovered)
			if (thoughtEvent.IsEmpty())
			{
				string sLeaderNow = GetPlayerLifeState();
				if (sLeaderNow != m_sLastLeaderState)
				{
					if (sLeaderNow == "downed")
						thoughtEvent = "leader_downed";
					else if (sLeaderNow == "alive" && m_sLastLeaderState == "downed")
						thoughtEvent = "leader_recovered";
					m_sLastLeaderState = sLeaderNow;
				}
			}

			if (thoughtEvent != "" && m_fThoughtCooldown >= 15.0)
			{
				m_fThoughtCooldown = 0;
				m_fThoughtTimer = 0;
				Print("[LLMBridge] Thought event: " + thoughtEvent);
				PollThoughts(thoughtEvent);
			}

			// Fallback: idle thoughts after 60s of no events
			if (m_fThoughtTimer >= 60.0)
			{
				m_fThoughtTimer = 0;
				m_fThoughtCooldown = 0;
				PollThoughts("idle");
			}
		}

		if (!m_bLLMReady)
		{
			m_fHealthCheckTimer += timeslice;
			if (m_fHealthCheckTimer >= 15.0)
			{
				m_fHealthCheckTimer = 0;
				CheckLLMHealth();
			}
		}
	}

	//------------------------------------------------------------------------------------------------
	void OnRestSuccess(string sEndpoint, string sData)
	{
		if (sEndpoint == "/health")
		{
			m_bLLMReady = true;
			Print("[LLMBridge] Bridge healthy, LLM mode active");
		}
		else if (sEndpoint == "/sitrep")
		{
			OnRadioCallback(sData);
		}
		else if (sEndpoint == "/orders")
		{
			ProcessOrders(sData);
		}
		else if (sEndpoint == "/ai_thought")
		{
			ProcessThoughts(sData);
		}
	}

	void OnRestError(string sEndpoint, int iErrorCode)
	{
		if (sEndpoint == "/health")
		{
			m_bLLMReady = false;
			m_bPassiveMode = true;
		}
	}

	void CheckLLMHealth()
	{
		EnsureRest();
		CreateCallback("/health");
		m_Rest.GET(m_aActiveCallbacks.Get(m_aActiveCallbacks.Count() - 1), "/health");
	}

	//------------------------------------------------------------------------------------------------
	// F6: Detect player downed/dead state
	// Uses public DamageManagerComponent API only (verified against local Workbench
	// ArmaReforgerScriptAPIPublic.zip docs + compiler):
	// - IsDestroyed()            -> dead  (proto external, public)
	// - GetHealthScaled() < 0.15 -> downed (critically low health = incapacitated)
	// NOTE: ShouldBeUnconscious() and IsIndefinitelyUnconscious() are PROTECTED
	// on SCR_CharacterDamageManagerComponent — not callable from our script.
	// Returns: "alive" | "downed" | "dead"
	string GetPlayerLifeState()
	{
		PlayerManager pm = GetGame().GetPlayerManager();
		if (!pm) return "alive";

		for (int pid = 1; pid <= 32; pid++)
		{
			IEntity playerEnt = pm.GetPlayerControlledEntity(pid);
			if (!playerEnt) continue;

			// F6: Damage manager (SCR_CharacterDamageManagerComponent extends SCR_DamageManagerComponent
			// extends DamageManagerComponent; FindComponent on the SCR_ subclass works and the
			// base public methods are inherited)
			SCR_DamageManagerComponent dmgMgr = SCR_DamageManagerComponent.Cast(
				playerEnt.FindComponent(SCR_DamageManagerComponent));
			if (!dmgMgr) return "alive";

			if (dmgMgr.IsDestroyed()) return "dead";

			// Downed: health critically low (incapacitated). GetHealthScaled() returns 0..1.
			if (dmgMgr.GetHealthScaled() < 0.15) return "downed";

			return "alive";
		}
		return "alive";
	}

	//------------------------------------------------------------------------------------------------
	void SendSITREP()
	{
		if (!m_bLLMReady) return;

		vector squadPos = GetSquadPosition();
		string sJSON = "{\"source\":\"game\",\"type\":\"SITREP\",\"position\":[" + squadPos[0] + "," + squadPos[1] + "," + squadPos[2] + "],\"squad\":[";
		for (int i = 0; i < m_aSquadMembers.Count(); i++)
		{
			if (i > 0) sJSON += ",";
			string s = m_aSquadMembers[i].m_sSITREP;
			if (s.IsEmpty()) s = "clear";
			sJSON += "{\"name\":\"" + m_aSquadMembers[i].m_sName + "\",\"order\":\"" + m_aSquadMembers[i].m_sCurrentOrder + "\",\"sitrep\":\"" + s + "\"}";
		}
		sJSON += "]";

		// F3.4: Add enemy info from StavkaController OPFOR groups
		int enemyCount = 0;
		string sEnemies = "[";
		if (g_StavkaInstance)
		{
			array<vector> enemyPos = g_StavkaInstance.GetEnemyPositions();
			enemyCount = enemyPos.Count();
			for (int e = 0; e < enemyPos.Count(); e++)
			{
				if (e > 0) sEnemies += ",";
				// Calculate relative offset from squad
				float dx = enemyPos[e][0] - squadPos[0];
				float dz = enemyPos[e][2] - squadPos[2];
				float dist = Math.Sqrt(dx * dx + dz * dz);
				sEnemies += "{\"dx\":" + dx + ",\"dz\":" + dz + ",\"dist\":" + dist + "}";
			}
		}
		sEnemies += "]";
		sJSON += ",\"enemies\":" + sEnemies + ",\"enemy_count\":" + enemyCount;
		m_iCurrentEnemyCount = enemyCount;

		// F3.5: Environment description
		string sEnv = ScanEnvironment(squadPos);

		// F6: Leader life state (alive/downed/dead)
		string sLeaderState = GetPlayerLifeState();
		if (sLeaderState != m_sLastLeaderState)
		{
			Print("[LLMBridge] Leader state changed: " + m_sLastLeaderState + " -> " + sLeaderState);
			m_sLastLeaderState = sLeaderState;
		}

		sJSON += ",\"environment\":\"" + sEnv + "\",\"leader_state\":\"" + sLeaderState + "\"}";


		EnsureRest();
		LLMBridgeRestCallback cb = CreateCallback("/sitrep");
		m_Rest.GET(cb, "/sitrep?data=" + UrlEncode(sJSON));
		Print("[LLMBridge] SITREP sent (pos=" + squadPos + ", enemies=" + enemyCount + ")");
	}

	//------------------------------------------------------------------------------------------------
	void UpdateStatus()
	{
		string sJSON = "{\"source\":\"game\",\"type\":\"STATUS\",\"llm_ready\":" + BoolStr(m_bLLMReady) + ",\"squad_count\":" + m_aSquadMembers.Count() + ",\"waypoint_count\":" + m_aWaypoints.Count() + "}";
		EnsureRest();
		LLMBridgeRestCallback cb = CreateCallback("/status");
		m_Rest.GET(cb, "/status?data=" + UrlEncode(sJSON));
	}

	//------------------------------------------------------------------------------------------------
	void PollOrders()
	{
		EnsureRest();
		LLMBridgeRestCallback cb = CreateCallback("/orders");
		m_Rest.GET(cb, "/orders");
	}

	//------------------------------------------------------------------------------------------------
	void ProcessOrders(string sData)
	{
		if (!sData || sData.IsEmpty()) return;

		int cmdIdx = sData.IndexOf("\"cmd\"");
		if (cmdIdx < 0) return;

		int colonIdx = sData.IndexOfFrom(cmdIdx, ":");
		if (colonIdx < 0) return;

		// Check for null
		int nullIdx = sData.IndexOfFrom(colonIdx, "null");
		if (nullIdx >= 0 && nullIdx < colonIdx + 10) return;

		int valStart = sData.IndexOfFrom(colonIdx, "\"");
		if (valStart < 0) return;
		int valEnd = sData.IndexOfFrom(valStart + 1, "\"");
		if (valEnd < 0) return;

		string cmd = sData.Substring(valStart + 1, valEnd - valStart - 1);
		Print("[LLMBridge] Live order received: " + cmd);

		if (cmd == "spawn")
		{
			Print("[LLMBridge] Executing spawn order...");
			// BUGFIX: was hardcoded LiveSpawnSquad(1) — after reconnect the player
			// may not be playerID 1. Find the first connected player dynamically.
			int spawnPid = GetFirstPlayerID();
			if (spawnPid > 0)
				SCR_AIWorld.LiveSpawnSquad(spawnPid);
			else
				Print("[LLMBridge] spawn order: no player connected");
		}
		else if (cmd == "hold")
		{
			SetAllOrders("HOLD");
			ClearSquadWaypoints();
			Print("[LLMBridge] HOLD order executed");
		}
		else if (cmd == "move" || cmd == "engage" || cmd == "attack" || cmd == "suppress" || cmd == "flank" || cmd == "retreat")
		{
			// NOTE: voice pipeline sends action.lower() (engage/suppress/flank/retreat) —
			// treat them as movement orders with the same offset parsing as "move".
			string moveAction = "MOVE";
			if (cmd == "engage" || cmd == "attack" || cmd == "suppress" || cmd == "flank")
				moveAction = "ATTACK";
			vector offset = "0 0 0";
			bool hasOffset = false;
			int offIdx = sData.IndexOf("\"offset\"");
			if (offIdx >= 0)
			{
				int offColon = sData.IndexOfFrom(offIdx, ":");
				int arrStart = sData.IndexOfFrom(offColon, "[");
				int arrEnd = -1;
				if (arrStart >= 0)  // guard: don't search from -1 (crash risk)
					arrEnd = sData.IndexOfFrom(arrStart, "]");
				if (arrStart >= 0 && arrEnd >= 0)
				{
					string arrStr = sData.Substring(arrStart + 1, arrEnd - arrStart - 1);
					float nums[2];
					int numCount = 0;
					int scan = 0;
					while (scan < arrStr.Length() && numCount < 2)
					{
						int comma = arrStr.IndexOfFrom(scan, ",");
						if (comma < 0) comma = arrStr.Length();
						string numStr = arrStr.Substring(scan, comma - scan);
						numStr.Replace(" ", "");
						if (!numStr.IsEmpty()) { nums[numCount] = numStr.ToFloat(); numCount++; }
						scan = comma + 1;
					}
					if (numCount >= 2) { offset[0] = nums[0]; offset[2] = nums[1]; hasOffset = true; }
				}
			}
			if (hasOffset)
			{
				vector squadPos = GetSquadPosition();
				vector targetPos = squadPos;
				targetPos[0] = squadPos[0] + offset[0];
				targetPos[2] = squadPos[2] + offset[2];
				Print("[LLMBridge] " + moveAction + ": squad=" + squadPos + " + offset=" + offset + " = " + targetPos);
				ExecuteWaypoint(moveAction, targetPos, true);  // CO order — LLM HOLD must not clear
			}
			else
			{
				Print("[LLMBridge] " + moveAction + " order but no offset provided");
			}
		}
		else if (cmd == "status")
		{
			vector pos = GetSquadPosition();
			SCR_AIGroup grp = FindPlayerGroup();
			int agentCount = 0;
			int memberCount = 0;
			int wpCount = 0;
			if (grp)
			{
				array<AIAgent> agents = {};
				grp.GetAgents(agents);
				agentCount = agents.Count();
				memberCount = grp.GetPlayerAndAgentCount();
				m_iCurrentSquadCount = memberCount;
				array<AIWaypoint> wps = {};
				grp.GetWaypoints(wps);
				wpCount = wps.Count();
			}
			Print("[LLMBridge] STATUS: pos=" + pos + " members=" + memberCount + " agents=" + agentCount + " waypoints=" + wpCount + " ready=" + BoolStr(m_bLLMReady));
		}
		else if (cmd == "prefabs")
		{
			Print("[LLMBridge] Checking group prefab slots...");
			SCR_AIWorld.LogGroupPrefabs();
		}
		else if (cmd == "despawn")
		{
			Print("[LLMBridge] Despawning all AI...");
			ClearSquadWaypoints();
			SCR_AIWorld.LiveDespawnSquad();
		}
		else if (cmd == "formation")
		{
			// Extract formation name from JSON
			string formName = "Column";
			int formIdx = sData.IndexOf("\"formation\"");
			if (formIdx >= 0)
			{
				int formColon = sData.IndexOfFrom(formIdx, ":");
				int formStart = sData.IndexOfFrom(formColon, "\"");
				int formEnd = -1;
				if (formStart >= 0)  // guard: don't search from formStart+1=0 (wrong match)
					formEnd = sData.IndexOfFrom(formStart + 1, "\"");
				if (formStart >= 0 && formEnd >= 0)
					formName = sData.Substring(formStart + 1, formEnd - formStart - 1);
			}
			Print("[LLMBridge] Setting formation: " + formName);
			SCR_AIWorld.SetGroupFormation(formName);
		}
		else if (cmd == "follow")
		{
			// Create a Follow waypoint at the leader's position
			vector leaderPos = GetSquadPosition();
			Print("[LLMBridge] FOLLOW: creating follow waypoint at " + leaderPos);
			ExecuteWaypoint("FOLLOW", leaderPos, true);  // CO order
		}
		else if (cmd == "medic")
		{
			// F8.3: Soldier tool call_medic queues this order — emergency rescue,
			// squad moves to the downed leader position (same logic as MEDIC action)
			SetAllOrders("MEDIC");
			vector medicPos = GetSquadPosition();
			Print("[LLMBridge] MEDIC: soldier tool triggered rescue at " + medicPos);
			ExecuteWaypoint("FOLLOW", medicPos, true);  // CO order
		}
		else if (cmd == "mount")
		{
			Print("[LLMBridge] MOUNT: ordering squad to enter nearest vehicle");
			SCR_AIWorld.MountNearestVehicle();
		}
		else if (cmd == "dismount")
		{
			Print("[LLMBridge] DISMOUNT: ordering squad to exit vehicle");
			SCR_AIWorld.DismountVehicle();
		}
		else if (cmd == "despawn_opfor")
		{
			Print("[LLMBridge] DESPAWN_OPFOR: clearing all OPFOR forces");
			if (g_StavkaInstance)
				g_StavkaInstance.DespawnAllOPFOR();
			else
				Print("[LLMBridge] No Stavka instance available");
		}
		else
		{
			Print("[LLMBridge] Unknown order: " + cmd);
		}
	}

	//------------------------------------------------------------------------------------------------
	void OnRadioCallback(string sMessage)
	{
		string action = "HOLD";
		vector offset = "0 0 0";
		bool hasOffset = false;

		int actionIdx = sMessage.IndexOf("\"action\"");
		if (actionIdx >= 0)
		{
			int colonIdx = sMessage.IndexOfFrom(actionIdx, ":");
			if (colonIdx >= 0)
			{
				int valStart = sMessage.IndexOfFrom(colonIdx, "\"");
				if (valStart >= 0)
				{
					int valEnd = sMessage.IndexOfFrom(valStart + 1, "\"");
					if (valEnd >= 0)
						action = sMessage.Substring(valStart + 1, valEnd - valStart - 1);
				}
			}
		}

		int posIdx = sMessage.IndexOf("\"target_offset\"");
		if (posIdx >= 0)
		{
			int posColon = sMessage.IndexOfFrom(posIdx, ":");
			if (posColon >= 0)
			{
				int arrStart = sMessage.IndexOfFrom(posColon, "[");
				if (arrStart >= 0)
				{
					int arrEnd = sMessage.IndexOfFrom(arrStart, "]");
					if (arrEnd >= 0)
					{
						string arrStr = sMessage.Substring(arrStart + 1, arrEnd - arrStart - 1);
						float nums[3];
						int numCount = 0;
						int scanStart = 0;
						while (scanStart < arrStr.Length() && numCount < 3)
						{
							int commaIdx = arrStr.IndexOfFrom(scanStart, ",");
							if (commaIdx < 0) commaIdx = arrStr.Length();
							string numStr = arrStr.Substring(scanStart, commaIdx - scanStart);
							numStr.Replace(" ", "");
							if (!numStr.IsEmpty()) { nums[numCount] = numStr.ToFloat(); numCount++; }
							scanStart = commaIdx + 1;
						}
						if (numCount >= 2) { offset[0] = nums[0]; offset[2] = nums[1]; hasOffset = true; }
					}
				}
			}
		}

		Print("[LLMBridge] LLM action=" + action + " offset=" + BoolStr(hasOffset));
		m_sCurrentLLMAction = action;

		if (action == m_sLastAction && action != "HOLD") return;
		m_sLastAction = action;

		if (action == "HOLD")
		{
			SetAllOrders("HOLD");
			// BUGFIX (2nd round): the LLM adjutant NEVER clears waypoints on HOLD.
			// Round 1 guarded only m_aWaypoints entries, but auto-follow waypoints
			// (RESPAWN path) and vanilla in-game commanding waypoints are added
			// DIRECTLY on the group — they are invisible to HasUserWaypoint() and
			// got wiped every 30s SITREP cycle, stopping the squad mid-move.
			// Only an explicit CO "hold" via /orders clears waypoints (CO wins).
			Print("[LLMBridge] HOLD from LLM — keeping waypoints active");
		}
		else if (action == "MOVE" || action == "ATTACK" || action == "FLANK" || action == "ENGAGE" || action == "SUPPRESS" || action == "RETREAT")
		{
			if (action == "SUPPRESS") action = "ATTACK";
			if (action == "RETREAT") action = "MOVE";
			if (action == "ENGAGE") action = "ATTACK";
			SetAllOrders(action);
			if (hasOffset)
			{
				vector squadPos = GetSquadPosition();
				vector targetPos = squadPos;
				targetPos[0] = squadPos[0] + offset[0];
				targetPos[2] = squadPos[2] + offset[2];
				ExecuteWaypoint(action, targetPos);
			}
			else
			{
				Print("[LLMBridge] " + action + " but no offset, holding");
				SetAllOrders("HOLD");
			}
		}
		else if (action == "MEDIC")
		{
			// F6: Emergency rescue — move squad to downed leader
			SetAllOrders("MEDIC");
			vector leaderPos = GetSquadPosition();
			Print("[LLMBridge] MEDIC: squad moving to rescue leader at " + leaderPos);
			ExecuteWaypoint("FOLLOW", leaderPos);
		}
		else
		{
			SetAllOrders("HOLD");
		}
	}

	//------------------------------------------------------------------------------------------------
	// F3.5: Scan environment - terrain, time of day
	string ScanEnvironment(vector squadPos)
	{
		// Get ChimeraWorld using CastFrom (NOT Cast - verified via Doxygen)
		ChimeraWorld world = ChimeraWorld.CastFrom(GetGame().GetWorld());
		if (!world) return "unknown terrain";
		
		TimeAndWeatherManagerEntity weatherMgr = world.GetTimeAndWeatherManager();
		if (!weatherMgr) return "unknown terrain";
		
		// Time info (verified APIs: GetTime() -> TimeContainer, IsSunSet() -> bool)
		TimeContainer time = weatherMgr.GetTime();
		int hours = time.m_iHours;
		int minutes = time.m_iMinutes;
		bool isNight = weatherMgr.IsSunSet();
		
		// Build time string (Enforce auto-converts int in string concat)
		string timeStr = "" + hours + ":";
		if (minutes < 10)
			timeStr += "0" + minutes;
		else
			timeStr += "" + minutes;
		
		string dayNight = "day";
		if (isNight) dayNight = "night";
		
		// Terrain description from elevation
		float baseHeight = squadPos[1];
		string terrain = "terrain at " + baseHeight + "m elevation";
		
		
		return timeStr + " " + dayNight + " - " + terrain;
	}

	//------------------------------------------------------------------------------------------------
	// Dynamic group lookup: if s_PlayerGroup is null, try to find it from player
	SCR_AIGroup FindPlayerGroup()
	{
		// First try the stored reference
		SCR_AIGroup grp = SCR_AIGroup.Cast(SCR_AIWorld.GetPlayerGroup());
		if (grp) return grp;

		// Not stored yet - try to find it from the player entity
		PlayerManager pm = GetGame().GetPlayerManager();
		if (!pm) return null;

		// Check players 1-32
		for (int pid = 1; pid <= 32; pid++)
		{
			IEntity playerEnt = pm.GetPlayerControlledEntity(pid);
			if (!playerEnt) continue;

			// Method 1: via SCR_PlayerControllerGroupComponent
			SCR_PlayerControllerGroupComponent groupComp = SCR_PlayerControllerGroupComponent.Cast(
				playerEnt.FindComponent(SCR_PlayerControllerGroupComponent));
			if (groupComp)
			{
				AIGroup rawGroup = groupComp.GetPlayersGroup();
				if (rawGroup)
				{
					SCR_AIGroup found = SCR_AIGroup.Cast(rawGroup);
					if (found)
					{
						Print("[LLMBridge] Found player group dynamically: " + found + " (player " + pid + ")");
						SCR_AIWorld.SetPlayerGroup(found);
						return found;
					}
				}
			}

			// Method 2: via AIControlComponent on player entity
			AIControlComponent aiCtrl = AIControlComponent.Cast(playerEnt.FindComponent(AIControlComponent));
			if (aiCtrl)
			{
				AIAgent playerAgent = aiCtrl.GetControlAIAgent();
				if (playerAgent)
				{
					AIGroup rawGroup = playerAgent.GetParentGroup();
					if (rawGroup)
					{
						SCR_AIGroup found = SCR_AIGroup.Cast(rawGroup);
						if (found)
						{
							Print("[LLMBridge] Found player group via AIControl: " + found + " (player " + pid + ")");
							SCR_AIWorld.SetPlayerGroup(found);
							return found;
						}
					}
				}
			}
		}

		return null;
	}

	//------------------------------------------------------------------------------------------------
	// Find the AI group: slave group if it exists (where AI agents live), else master group
	SCR_AIGroup FindAIGroup()
	{
		SCR_AIGroup master = FindPlayerGroup();
		if (!master) return null;

		// AI agents are in the SLAVE group, not the master group!
		SCR_AIGroup slave = master.GetSlave();
		if (slave)
		{
			Print("[LLMBridge] Using SLAVE group for AI: " + slave);
			return slave;
		}

		// No slave group - fall back to master (singleplayer or no AI spawned yet)
		return master;
	}

	//------------------------------------------------------------------------------------------------
	vector GetSquadPosition()
	{
		// Try slave group first (where AI agents live)
		SCR_AIGroup grp = FindAIGroup();
		if (grp)
		{
			array<AIAgent> agents = {};
			grp.GetAgents(agents);
			if (agents.Count() > 0)
			{
				IEntity ent = agents[0].GetControlledEntity();
				if (ent) return ent.GetOrigin();
			}
		}
		// Fall back to player position (squad follows player anyway)
		PlayerManager pm = GetGame().GetPlayerManager();
		if (pm)
		{
			for (int pid = 1; pid <= 32; pid++)
			{
				IEntity playerEnt = pm.GetPlayerControlledEntity(pid);
				if (playerEnt) return playerEnt.GetOrigin();
			}
		}
		return "0 0 0";
	}

	//------------------------------------------------------------------------------------------------
	// Returns true if the CO (user) placed an active waypoint via /orders
	// (dashboard/voice). The LLM adjutant's HOLD must NOT clear these —
	// the CO outranks the adjutant.
	bool HasUserWaypoint()
	{
		for (int i = 0; i < m_aWaypoints.Count(); i++)
		{
			if (m_aWaypoints[i].m_bUserOrder)
				return true;
		}
		return false;
	}

	//------------------------------------------------------------------------------------------------
	void ExecuteWaypoint(string sAction, vector vPos, bool bUserOrder = false)
	{
		SCR_AIGroup grp = FindAIGroup();
		if (!grp) { Print("[LLMBridge] No AI group found (slave or master)"); return; }
		if (!Replication.IsServer()) return;

		string prefabName = WP_MOVE;
		if (sAction == "ATTACK") prefabName = WP_ATTACK;
		else if (sAction == "DEFEND") prefabName = WP_DEFEND;
		else if (sAction == "FOLLOW") prefabName = WP_FOLLOW;

		Resource res = Resource.Load(prefabName);
		if (!res || !res.IsValid()) { Print("[LLMBridge] Bad waypoint prefab"); return; }

		EntitySpawnParams spawnParams = new EntitySpawnParams();
		spawnParams.TransformMode = ETransformMode.WORLD;
		spawnParams.Transform[3] = vPos;

		IEntity wpEntity = GetGame().SpawnEntityPrefab(res, GetGame().GetWorld(), spawnParams);
		AIWaypoint wp = AIWaypoint.Cast(wpEntity);
		if (!wp) { Print("[LLMBridge] Not an AIWaypoint"); return; }

		wp.SetCompletionRadius(15.0);
		ClearSquadWaypoints();
		grp.AddWaypoint(wp);
		Print("[LLMBridge] Waypoint at " + vPos + " (" + sAction + ") on group " + grp);

		string sID = "WP_" + sAction + "_" + m_aWaypoints.Count();
		LLMWaypoint lwp = new LLMWaypoint(sID, vPos, sAction);
		lwp.m_fSpawnTime = m_fTime;
		lwp.m_bUserOrder = bUserOrder;
		m_aWaypoints.Insert(lwp);
	}

	void ClearSquadWaypoints()
	{
		SCR_AIGroup grp = FindAIGroup();
		if (!grp) return;
		array<AIWaypoint> existing = {};
		grp.GetWaypoints(existing);
		foreach (AIWaypoint wp : existing)
		{
			if (wp) grp.RemoveWaypoint(wp);
		}
		if (existing.Count() > 0)
			Print("[LLMBridge] Cleared " + existing.Count() + " waypoints from AI group");
	}

	void SetAllOrders(string sOrder)
	{
		for (int i = 0; i < m_aSquadMembers.Count(); i++)
			m_aSquadMembers[i].m_sCurrentOrder = sOrder;
	}

	//------------------------------------------------------------------------------------------------
	// Find the first connected player ID (1-32), or 0 if none
	int GetFirstPlayerID()
	{
		PlayerManager pm = GetGame().GetPlayerManager();
		if (!pm) return 0;
		for (int pid = 1; pid <= 32; pid++)
		{
			if (pm.GetPlayerControlledEntity(pid))
				return pid;
		}
		return 0;
	}

	//------------------------------------------------------------------------------------------------
	// F2.7: Individual AI Brains — poll and display thoughts
	void PollThoughts(string thoughtEvent = "")
	{
		EnsureRest();
		LLMBridgeRestCallback cb = CreateCallback("/ai_thought");
		m_Rest.GET(cb, "/ai_thought?event=" + thoughtEvent);
	}

	//------------------------------------------------------------------------------------------------
	// F8.3: Parse optional "tool" field from a thought JSON object.
	// Returns empty string if no tool. Tool block: {"name": "call_medic", "args": {...}}
	// BUGFIX: the search is bounded to the CURRENT object (first '}' after the
	// thought) so a tool from a LATER thought can't be misattributed to this one.
	string ExtractThoughtTool(string sData, int scanFrom, out int scanEnd)
	{
		scanEnd = scanFrom;

		// Find the end of the current thought object: first '}' after scanFrom
		int objEnd = sData.IndexOfFrom(scanFrom, "}");
		if (objEnd < 0) return "";

		// Only search for "tool" within this object's span
		int toolIdx = sData.IndexOfFrom(scanFrom, "\"tool\"");
		if (toolIdx < 0 || toolIdx > objEnd) return "";

		// Find tool name (first string value after "tool")
		int nameIdx = sData.IndexOfFrom(toolIdx, "\"name\"");
		if (nameIdx < 0 || nameIdx > objEnd) return "";
		int colon = sData.IndexOfFrom(nameIdx, ":");
		if (colon < 0) return "";
		int start = sData.IndexOfFrom(colon, "\"");
		if (start < 0) return "";
		int end = sData.IndexOfFrom(start + 1, "\"");
		if (end < 0 || end > objEnd) return "";
		scanEnd = end + 1;
		return sData.Substring(start + 1, end - start - 1);
	}

	//------------------------------------------------------------------------------------------------
	void ProcessThoughts(string sData)
	{
		if (!sData || sData.IsEmpty()) return;

		// Parse JSON: {"thoughts": [{"name": "Alpha_1", "thought": "...", "mood": "..."}, ...]}
		// Simple string-based parser (Enforce has no JSON library)
		int scanPos = 0;
		int thoughtCount = 0;

		while (scanPos < sData.Length())
		{
			// Find next "name" field
			int nameIdx = sData.IndexOfFrom(scanPos, "\"name\"");
			if (nameIdx < 0) break;

			// Extract name value
			int nameColon = sData.IndexOfFrom(nameIdx, ":");
			if (nameColon < 0) break;
			int nameStart = sData.IndexOfFrom(nameColon, "\"");
			if (nameStart < 0) break;
			int nameEnd = sData.IndexOfFrom(nameStart + 1, "\"");
			if (nameEnd < 0) break;

			string name = sData.Substring(nameStart + 1, nameEnd - nameStart - 1);

			// Find "thought" field after this name
			int thoughtIdx = sData.IndexOfFrom(nameEnd, "\"thought\"");
			if (thoughtIdx < 0) break;
			int thoughtColon = sData.IndexOfFrom(thoughtIdx, ":");
			if (thoughtColon < 0) break;
			int thoughtStart = sData.IndexOfFrom(thoughtColon, "\"");
			if (thoughtStart < 0) break;
			int thoughtEnd = sData.IndexOfFrom(thoughtStart + 1, "\"");
			if (thoughtEnd < 0) break;

			string thought = sData.Substring(thoughtStart + 1, thoughtEnd - thoughtStart - 1);

			// F8.3: Check for optional tool call after this thought
			int toolEnd = 0;
			string toolName = ExtractThoughtTool(sData, thoughtEnd, toolEnd);
			if (toolEnd > 0) scanPos = toolEnd; else scanPos = thoughtEnd + 1;

			// Display via chat
			string chatMsg = "[" + name + "] " + thought;

			// F8.3: Append tool call to the message so agent actions are visible in-game
			if (!toolName.IsEmpty())
			{
				chatMsg = chatMsg + " (" + toolName + ")";
				Print("[LLMBridge] AI tool call: " + name + " -> " + toolName);
			}

			// Try chat display (may work on client, may not on DS)
			SCR_ChatComponent.RadioProtocolMessage(chatMsg);

			// Always log
			Print("[LLMBridge] AI thought: " + chatMsg);

			thoughtCount++;
		}

		if (thoughtCount > 0)
			Print("[LLMBridge] Processed " + thoughtCount + " AI thoughts");
	}
}
