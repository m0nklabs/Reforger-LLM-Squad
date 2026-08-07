// LLMBridge.c - LLM Squad Control Bridge for Arma Reforger
// Phase 1: REST bridge + AI squad control (no voice)
//
// Fixed 2026-08-07:
//  - 'modclass' does not exist in Enforce -> 'class'
//  - Nested classes removed (Enforce does not allow class-in-class) ->
//    LLMSquadMember / LLMWaypoint are now file-scope (also renamed to avoid
//    collision with the engine class 'Waypoint')
//  - Invented REST API (new RestContext/SetMethod/Start) replaced with the real one:
//    GetGame().GetRestApi().GetContext(baseUrl) + GET/POST + RestCallback
//    (wiki: Arma_Reforger:REST_API_Usage)
//  - 'override' removed: no base class. Activate()/Update() will be called (F1.2)
//    from a GameMode component.
//  - Ternary expressions and bool-concat removed from string building (compile-safe)
//
// TODO (F1.2): instantiate LLMBridge from a component (e.g. modded
//              SCR_BaseGameMode) and call Activate()/Update().
// TODO:        system_prompt lives server-side (python_bridge) - keep it there.

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
	string m_sType; // "PATROL", "ATTACK", "DEFEND", "MOVE"
	bool m_bExecuted;
	float m_fSpawnTime;

	void LLMWaypoint(string sID, vector vPos, string sType)
	{
		m_sID = sID;
		m_vPosition = vPos;
		m_sType = sType;
		m_bExecuted = false;
		m_fSpawnTime = 0.0; // set by LLMBridge.SpawnWaypoint (m_fTime)
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
	}

	override void OnSuccess(string data, int dataSize)
	{
		Print("[LLMBridge] REST " + m_sEndpoint + " OK (" + dataSize + " bytes)");
		if (m_pOwner)
			m_pOwner.OnRestSuccess(m_sEndpoint, data);
	}

	override void OnError(int errorCode)
	{
		Print("[LLMBridge] REST " + m_sEndpoint + " ERROR " + errorCode);
		if (m_pOwner)
			m_pOwner.OnRestError(m_sEndpoint, errorCode);
	}
}

//------------------------------------------------------------------------------------------------
class LLMBridge
{
	// ===== Configuration =====
	string m_sPythonBridgeURL;   // e.g. "http://127.0.0.1:5001"
	string m_sLLMModel;          // e.g. "llama3"
	float m_fLLMTimeout;         // seconds (default 3.0)
	float m_fSITREPInterval;     // seconds between SITREPs (default 10.0)
	float m_fLLMCALLInterval;    // min seconds between LLM calls (default 2.0)

	// Squad members to control
	ref array<ref LLMSquadMember> m_aSquadMembers;

	// ===== State =====
	bool m_bLLMReady;
	bool m_bPassiveMode;

	// REST (real Enfusion API)
	RestContext m_Rest; // non-ref! RestApi owns the context (destructor is private)

	// Waypoints managed by LLM
	ref array<ref LLMWaypoint> m_aWaypoints;

	// Timers (m_fTime accumulates via Update timeslice, in seconds)
	float m_fTime;
	float m_fLastSITREP;
	float m_fLastLLMCall;
	float m_fSITREPTimer;
	float m_fStatusTimer;

	//------------------------------------------------------------------------------------------------
	void LLMBridge()
	{
		m_sPythonBridgeURL = "http://127.0.0.1:5001"; // must match python_bridge/config.json
		m_sLLMModel = "llama3";
		m_fLLMTimeout = 3.0;
		m_fSITREPInterval = 10.0;
		m_fLLMCALLInterval = 2.0;
		m_bLLMReady = false;
		m_bPassiveMode = false;
		m_fTime = 0.0;
		m_fLastSITREP = 0.0;
		m_fLastLLMCall = 0.0;
		m_fSITREPTimer = 0.0;
		m_fStatusTimer = 0.0;

		m_aSquadMembers = new array<ref LLMSquadMember>;
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_1"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_2"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_3"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_4"));

		m_aWaypoints = new array<ref LLMWaypoint>;

		Print("[LLMBridge] Initialized (bridge URL: " + m_sPythonBridgeURL + ")");
	}

	//------------------------------------------------------------------------------------------------
	protected void EnsureRest()
	{
		if (!m_Rest)
		{
			m_Rest = GetGame().GetRestApi().GetContext(m_sPythonBridgeURL);
			Print("[LLMBridge] REST context created for " + m_sPythonBridgeURL);
		}
	}

	protected string BoolStr(bool b)
	{
		if (b)
			return "true";
		return "false";
	}

	//------------------------------------------------------------------------------------------------
	// Called later (F1.2) from a component
	void Activate()
	{
		Print("[LLMBridge] Activated");
		EnsureRest();
		CheckLLMHealth();
	}

	// Called later (F1.2) from a component's OnUpdate
	void Update(float timeslice)
	{
		m_fTime += timeslice;
		m_fSITREPTimer += timeslice;
		if (m_fSITREPTimer >= m_fSITREPInterval)
		{
			m_fSITREPTimer = 0.0;
			SendSITREP();
		}

		m_fStatusTimer += timeslice;
		if (m_fStatusTimer >= 5.0)
		{
			m_fStatusTimer = 0.0;
			UpdateStatus();
		}

		CheckWaypoints(timeslice);
	}

	// ===== REST callbacks =====
	//------------------------------------------------------------------------------------------------
	void OnRestSuccess(string sEndpoint, string sData)
	{
		if (sEndpoint == "/health")
		{
			m_bLLMReady = true;
			m_bPassiveMode = false;
			Print("[LLMBridge] Bridge healthy, LLM mode active");
		}
		else if (sEndpoint == "/command")
		{
			OnRadioCallback(sData);
		}
	}

	//------------------------------------------------------------------------------------------------
	void OnRestError(string sEndpoint, int iErrorCode)
	{
		if (sEndpoint == "/health")
		{
			m_bLLMReady = false;
			m_bPassiveMode = true;
			Print("[LLMBridge] Bridge unreachable -> passive mode (HOLD)");
		}
	}

	// ===== LLM Health Check =====
	//------------------------------------------------------------------------------------------------
	void CheckLLMHealth()
	{
		EnsureRest();
		Print("[LLMBridge] Checking bridge health: " + m_sPythonBridgeURL + "/health");
		m_Rest.GET(new LLMBridgeRestCallback(this, "/health"), "/health");
	}

	// ===== SITREP Collection =====
	//------------------------------------------------------------------------------------------------
	void SendSITREP()
	{
		if (!m_bLLMReady && !m_bPassiveMode)
		{
			Print("[LLMBridge] LLM not ready, skipping SITREP");
			return;
		}

		string sJSON = "{\"source\": \"game\", \"type\": \"SITREP\", \"squad\": [";
		for (int i = 0; i < m_aSquadMembers.Count(); i++)
		{
			if (i > 0)
				sJSON += ",";

			string sSitrep = m_aSquadMembers[i].m_sSITREP;
			if (sSitrep.IsEmpty())
				sSitrep = "clear";

			sJSON += "{\"name\": \"" + m_aSquadMembers[i].m_sName + "\", ";
			sJSON += "\"order\": \"" + m_aSquadMembers[i].m_sCurrentOrder + "\", ";
			sJSON += "\"sitrep\": \"" + sSitrep + "\"}";
		}
		sJSON += "]}";

		EnsureRest();
		m_Rest.POST(new LLMBridgeRestCallback(this, "/sitrep"), "/sitrep", sJSON);
		m_fLastSITREP = m_fTime;
		Print("[LLMBridge] SITREP sent");
	}

	// ===== Command Routing =====
	//------------------------------------------------------------------------------------------------
	void SendCommand(string sCommand)
	{
		float fNow = m_fTime;
		if (fNow - m_fLastLLMCall < m_fLLMCALLInterval)
		{
			Print("[LLMBridge] LLM call rate limited: " + sCommand);
			return;
		}

		string sJSON = "{";
		sJSON += "\"source\": \"game\", ";
		sJSON += "\"type\": \"COMMAND\", ";
		sJSON += "\"command\": \"" + sCommand + "\", ";
		sJSON += "\"model\": \"" + m_sLLMModel + "\"";
		sJSON += "}";

		EnsureRest();
		m_Rest.POST(new LLMBridgeRestCallback(this, "/command"), "/command", sJSON);
		m_fLastLLMCall = fNow;
		Print("[LLMBridge] Command sent: " + sCommand);
	}

	// ===== Status Update =====
	//------------------------------------------------------------------------------------------------
	void UpdateStatus()
	{
		string sJSON = "{";
		sJSON += "\"source\": \"game\", ";
		sJSON += "\"type\": \"STATUS\", ";
		sJSON += "\"llm_ready\": " + BoolStr(m_bLLMReady) + ", ";
		sJSON += "\"passive_mode\": " + BoolStr(m_bPassiveMode) + ", ";
		sJSON += "\"squad_count\": " + m_aSquadMembers.Count() + ", ";
		sJSON += "\"waypoint_count\": " + m_aWaypoints.Count();
		sJSON += "}";

		EnsureRest();
		m_Rest.POST(new LLMBridgeRestCallback(this, "/status"), "/status", sJSON);
	}

	// ===== Waypoint Management =====
	//------------------------------------------------------------------------------------------------
	void SpawnWaypoint(vector vPos, string sType)
	{
		string sID = "WP_" + sType + "_" + m_aWaypoints.Count();
		LLMWaypoint wp = new LLMWaypoint(sID, vPos, sType);
		wp.m_fSpawnTime = m_fTime;
		m_aWaypoints.Insert(wp);

		Print("[LLMBridge] Waypoint spawned: " + sID + " at " + vPos.ToString());

		string sJSON = "{";
		sJSON += "\"source\": \"game\", ";
		sJSON += "\"type\": \"WAYPOINT\", ";
		sJSON += "\"id\": \"" + sID + "\", ";
		sJSON += "\"position\": [" + vPos[0] + ", " + vPos[1] + ", " + vPos[2] + "], ";
		sJSON += "\"wp_type\": \"" + sType + "\"";
		sJSON += "}";

		EnsureRest();
		m_Rest.POST(new LLMBridgeRestCallback(this, "/waypoint"), "/waypoint", sJSON);
	}

	//------------------------------------------------------------------------------------------------
	void CheckWaypoints(float timeslice)
	{
		for (int i = 0; i < m_aWaypoints.Count(); i++)
		{
			LLMWaypoint wp = m_aWaypoints[i];
			if (!wp.m_bExecuted)
			{
				float fAge = m_fTime - wp.m_fSpawnTime;
				if (fAge > 30.0) // 30 seconds
				{
					wp.m_bExecuted = true;
					Print("[LLMBridge] Waypoint " + wp.m_sID + " timed out");
				}
			}
		}
	}

	// ===== Radio Callback (LLM response -> orders) =====
	//------------------------------------------------------------------------------------------------
	void OnRadioCallback(string sMessage)
	{
		Print("[LLMBridge] Radio callback: " + sMessage);

		if (sMessage.Contains("HOLD"))
			SetAllOrders("HOLD");
		else if (sMessage.Contains("ATTACK"))
			SetAllOrders("ATTACK");
		else if (sMessage.Contains("PATROL"))
			SetAllOrders("PATROL");
	}

	//------------------------------------------------------------------------------------------------
	void SetAllOrders(string sOrder)
	{
		for (int i = 0; i < m_aSquadMembers.Count(); i++)
		{
			m_aSquadMembers[i].m_sCurrentOrder = sOrder;
		}
		Print("[LLMBridge] All squad orders set to: " + sOrder);
	}

	// ===== Public API =====
	//------------------------------------------------------------------------------------------------
	void SetSquadOrder(string sMemberName, string sOrder)
	{
		for (int i = 0; i < m_aSquadMembers.Count(); i++)
		{
			if (m_aSquadMembers[i].m_sName == sMemberName)
			{
				m_aSquadMembers[i].m_sCurrentOrder = sOrder;
				Print("[LLMBridge] " + sMemberName + " ordered: " + sOrder);
				return;
			}
		}
		Print("[LLMBridge] Squad member not found: " + sMemberName);
	}

	//------------------------------------------------------------------------------------------------
	void SendSITREPToPython(string sMemberName, string sSITREP)
	{
		for (int i = 0; i < m_aSquadMembers.Count(); i++)
		{
			if (m_aSquadMembers[i].m_sName == sMemberName)
			{
				m_aSquadMembers[i].m_sSITREP = sSITREP;
				break;
			}
		}
	}

	//------------------------------------------------------------------------------------------------
	void SetPassiveMode(bool bPassive)
	{
		m_bPassiveMode = bPassive;
		Print("[LLMBridge] Passive mode: " + BoolStr(bPassive));
	}

	//------------------------------------------------------------------------------------------------
	void Log(string sMessage)
	{
		Print("[LLMBridge] " + sMessage);
	}
}
