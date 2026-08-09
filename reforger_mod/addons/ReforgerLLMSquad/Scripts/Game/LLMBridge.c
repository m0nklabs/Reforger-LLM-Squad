// LLMBridge.c - LLM Squad Control Bridge for Arma Reforger
// Phase 1: REST bridge + AI squad control (no voice)
//
// F1.3 (2026-08-09): Route sync — two critical REST API bugs fixed:
//   1. Callback GC: inline `new RestCallback(...)` is GC'd before async response.
//      Fix: store in ref array (m_aActiveCallbacks) to keep alive.
//   2. POST body empty: Enforce POST(cb, path, body) sends HTTP but body never arrives.
//      Fix: send data via GET query param (/sitrep?data=<urlencoded_json>).
//   Both SetOnSuccess (modern) and OnSuccess (deprecated override) fire correctly
//   once the callback survives GC. We use SetOnSuccess in the constructor.

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

	void LLMWaypoint(string sID, vector vPos, string sType)
	{
		m_sID = sID;
		m_vPosition = vPos;
		m_sType = sType;
		m_bExecuted = false;
		m_fSpawnTime = 0.0;
	}
}

//------------------------------------------------------------------------------------------------
// REST callback — extends RestCallback.
// SetOnSuccess/SetOnError are called in the constructor (modern API).
// The deprecated OnSuccess/OnError overrides are kept as fallback (they also fire).
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
		Print("[LLMBridge] REST " + m_sEndpoint + " OK");
		if (m_pOwner)
			m_pOwner.OnRestSuccess(m_sEndpoint, "");
	}

	void ErrorHandler(RestCallback cb = null)
	{
		Print("[LLMBridge] REST " + m_sEndpoint + " ERROR");
		if (m_pOwner)
			m_pOwner.OnRestError(m_sEndpoint, 0);
	}

	override void OnSuccess(string data, int dataSize)
	{
		Print("[LLMBridge] REST " + m_sEndpoint + " OnSuccess data=" + data + " size=" + dataSize);
		if (m_pOwner)
			m_pOwner.OnRestSuccess(m_sEndpoint, data);
	}

	override void OnError(int errorCode)
	{
		Print("[LLMBridge] REST " + m_sEndpoint + " OnError code=" + errorCode);
		if (m_pOwner)
			m_pOwner.OnRestError(m_sEndpoint, errorCode);
	}
}

//------------------------------------------------------------------------------------------------
class LLMBridge
{
	// ===== Configuration =====
	string m_sPythonBridgeURL;
	string m_sLLMModel;
	float m_fLLMTimeout;
	float m_fSITREPInterval;
	float m_fLLMCALLInterval;

	// Squad members
	ref array<ref LLMSquadMember> m_aSquadMembers;

	// ===== State =====
	bool m_bLLMReady;
	bool m_bPassiveMode;

	// REST
	RestContext m_Rest; // non-ref! RestApi owns the context

	// Active callbacks — MUST be ref to prevent GC before async response (F1.3 fix)
	ref array<ref LLMBridgeRestCallback> m_aActiveCallbacks;

	// Waypoints
	ref array<ref LLMWaypoint> m_aWaypoints;

	// Timers
	float m_fTime;
	float m_fLastSITREP;
	float m_fLastLLMCall;
	float m_fSITREPTimer;
	float m_fStatusTimer;
	float m_fHealthCheckTimer;

	//------------------------------------------------------------------------------------------------
	void LLMBridge()
	{
		m_sPythonBridgeURL = "http://127.0.0.1:5001";
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
		m_fHealthCheckTimer = 0.0;

		m_aSquadMembers = new array<ref LLMSquadMember>;
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_1"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_2"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_3"));
		m_aSquadMembers.Insert(new LLMSquadMember("Alpha_4"));

		m_aWaypoints = new array<ref LLMWaypoint>;
		m_aActiveCallbacks = new array<ref LLMBridgeRestCallback>;

		Print("[LLMBridge] Initialized (bridge URL: " + m_sPythonBridgeURL + ")");
	}

	//------------------------------------------------------------------------------------------------
	// Create callback and store in ref array to prevent GC before async response
	protected LLMBridgeRestCallback CreateCallback(string sEndpoint)
	{
		LLMBridgeRestCallback cb = new LLMBridgeRestCallback(this, sEndpoint);
		m_aActiveCallbacks.Insert(cb);
		while (m_aActiveCallbacks.Count() > 20)
			m_aActiveCallbacks.RemoveOrdered(0);
		return cb;
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
	// URL-encode for GET query params (Enforce has no built-in encoder)
	protected string UrlEncode(string s)
	{
		string result = "";
		for (int i = 0; i < s.Length(); i++)
		{
			string ch = s.Get(i);
			if (ch == " ")
				result += "%20";
			else if (ch == "\"")
				result += "%22";
			else if (ch == "{")
				result += "%7B";
			else if (ch == "}")
				result += "%7D";
			else if (ch == "[")
				result += "%5B";
			else if (ch == "]")
				result += "%5D";
			else if (ch == ":")
				result += "%3A";
			else if (ch == ",")
				result += "%2C";
			else
				result += ch;
		}
		return result;
	}

	//------------------------------------------------------------------------------------------------
	void Activate()
	{
		Print("[LLMBridge] Activated");
		EnsureRest();
		CheckLLMHealth();
	}

	//------------------------------------------------------------------------------------------------
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

		if (!m_bLLMReady)
		{
			m_fHealthCheckTimer += timeslice;
			if (m_fHealthCheckTimer >= 15.0)
			{
				m_fHealthCheckTimer = 0.0;
				CheckLLMHealth();
			}
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
		LLMBridgeRestCallback cb = CreateCallback("/health");
		m_Rest.GET(cb, "/health");
	}

	// ===== SITREP Collection =====
	//------------------------------------------------------------------------------------------------
	void SendSITREP()
	{
		if (!m_bLLMReady)
		{
			Print("[LLMBridge] LLM not ready, skipping SITREP");
			return;
		}

		string sJSON = "{\"source\":\"game\",\"type\":\"SITREP\",\"squad\":[";
		for (int i = 0; i < m_aSquadMembers.Count(); i++)
		{
			if (i > 0)
				sJSON += ",";

			string sSitrep = m_aSquadMembers[i].m_sSITREP;
			if (sSitrep.IsEmpty())
				sSitrep = "clear";

			sJSON += "{\"name\":\"" + m_aSquadMembers[i].m_sName + "\",";
			sJSON += "\"order\":\"" + m_aSquadMembers[i].m_sCurrentOrder + "\",";
			sJSON += "\"sitrep\":\"" + sSitrep + "\"}";
		}
		sJSON += "]}";

		EnsureRest();
		// Send via GET query param (POST body doesn't transmit in Enforce)
		LLMBridgeRestCallback cb = CreateCallback("/sitrep");
		m_Rest.GET(cb, "/sitrep?data=" + UrlEncode(sJSON));
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

		string sJSON = "{\"source\":\"game\",\"type\":\"COMMAND\",\"command\":\"" + sCommand + "\",\"model\":\"" + m_sLLMModel + "\"}";

		EnsureRest();
		LLMBridgeRestCallback cb = CreateCallback("/command");
		m_Rest.GET(cb, "/command?data=" + UrlEncode(sJSON));
		m_fLastLLMCall = fNow;
		Print("[LLMBridge] Command sent: " + sCommand);
	}

	// ===== Status Update =====
	//------------------------------------------------------------------------------------------------
	void UpdateStatus()
	{
		string sJSON = "{\"source\":\"game\",\"type\":\"STATUS\",\"llm_ready\":" + BoolStr(m_bLLMReady) + ",\"passive_mode\":" + BoolStr(m_bPassiveMode) + ",\"squad_count\":" + m_aSquadMembers.Count() + ",\"waypoint_count\":" + m_aWaypoints.Count() + "}";

		EnsureRest();
		LLMBridgeRestCallback cb = CreateCallback("/status");
		m_Rest.GET(cb, "/status?data=" + UrlEncode(sJSON));
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

		string sJSON = "{\"source\":\"game\",\"type\":\"WAYPOINT\",\"id\":\"" + sID + "\",\"position\":[" + vPos[0] + "," + vPos[1] + "," + vPos[2] + "],\"wp_type\":\"" + sType + "\"}";

		EnsureRest();
		LLMBridgeRestCallback cb = CreateCallback("/waypoint");
		m_Rest.GET(cb, "/waypoint?data=" + UrlEncode(sJSON));
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
				if (fAge > 30.0)
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
