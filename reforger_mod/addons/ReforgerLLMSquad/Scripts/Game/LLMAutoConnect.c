// LLMAutoConnect.c - Auto-connect to dedicated server via profile JSON config
//
// Step 0 verification (completed 2026-08-08):
//   FileIO.FileExists           → VERIFIED (Core/generated/System/FileIO.c, proto bool, $profile: OK)
//   SCR_JsonLoadContext         → VERIFIED (deprecated alias of JsonLoadContext; LoadFromFile/ReadValue real)
//   SCR_JsonSaveContext         → VERIFIED (deprecated alias of JsonSaveContext; WriteValue/SaveToFile real)
//   GetGame().GetBackendApi()   → VERIFIED (GameLib/generated/online/BackendApi.c)
//
// BLOCKER (invented API in original spec):
//   GetBackendApi().GetDSModule().DirectConnect(ip, port, password)  → DOES NOT EXIST
//   - GetDSModule() is NOT a method on BackendApi (real: GetClientLobby() + GetDSSession())
//   - DirectConnect(ip,port,pw) returns zero results in official Doxygen AND community code
//   - Vanilla join path = ServerBrowserMenuUI.JoinActions_DirectJoin() → JoinProcess_FindRoomById()
//     → JoinProcess_OnFindRoomSuccess(Room) → JoinProcess_Init(Room) → JoinProcess_Join()
//   - Steam discussions confirm -client ip:port yields "invalid session ticket" (backend auth gated)
//
// Current strategy:
//   Read JSON + self-disable = fully implemented with verified APIs.
//   Connect call             = STUBBED with diagnostic logging (no invented APIs per AGENTS.md rules).
//   Next phase               = research ClientLobby.FindRoomByIp() or drive menu-based JoinActions_DirectJoin().

//------------------------------------------------------------------------------------------------
class LLMAutoConnect
{
    static const string CONFIG_PATH = "$profile:agent_auto_connect.json";

    // Config values (read from JSON)
    bool   m_bEnabled;
    string m_sServerIp;
    int    m_iServerPort;
    string m_sPassword;

    // State
    bool   m_bConfigLoaded;
    bool   m_bAttempted;
    float  m_fTimer;

    //------------------------------------------------------------------------------------------------
    void LLMAutoConnect()
    {
        m_bEnabled = false;
        m_sServerIp = "127.0.0.1";
        m_iServerPort = 2001;
        m_sPassword = "";
        m_bConfigLoaded = false;
        m_bAttempted = false;
        m_fTimer = 0.0;

        Print("[LLMAutoConnect] Component constructed");
    }

    //------------------------------------------------------------------------------------------------
    // Entry point — called from OnGameStart() via Callqueue delay
    void CheckAndConnect()
    {
        if (m_bAttempted)
        {
            Print("[LLMAutoConnect] Already attempted, skipping");
            return;
        }
        m_bAttempted = true;

        Print("[LLMAutoConnect] Checking config: " + CONFIG_PATH);

        // --- Step 1: Check if config file exists (verified API: FileIO.FileExists) ---
        if (!FileIO.FileExists(CONFIG_PATH))
        {
            Print("[LLMAutoConnect] Config file not found, exiting");
            return;
        }

        // --- Step 2: Load JSON config (verified API: SCR_JsonLoadContext.LoadFromFile/ReadValue) ---
        SCR_JsonLoadContext loadContext = new SCR_JsonLoadContext();
        if (!loadContext.LoadFromFile(CONFIG_PATH))
        {
            Print("[LLMAutoConnect] ERROR: Failed to load config from " + CONFIG_PATH);
            return;
        }

        m_bConfigLoaded = true;
        loadContext.ReadValue("enabled", m_bEnabled);
        loadContext.ReadValue("server_ip", m_sServerIp);
        loadContext.ReadValue("server_port", m_iServerPort);
        loadContext.ReadValue("password", m_sPassword);

        string enabledStr = "false";
        if (m_bEnabled)
            enabledStr = "true";

        Print("[LLMAutoConnect] Config loaded: enabled=" + enabledStr + " ip=" + m_sServerIp + " port=" + m_iServerPort);

        if (!m_bEnabled)
        {
            Print("[LLMAutoConnect] Auto-connect disabled in config, exiting");
            return;
        }

        // --- Step 3: Self-disable immediately to prevent connection loops on restart ---
        // (verified API: SCR_JsonSaveContext.WriteValue/SaveToFile)
        SaveDisabledConfig();

        // --- Step 4: Attempt connection ---
        // BackendApi is verified real, but GetDSModule().DirectConnect() is INVENTED.
        // The real vanilla flow goes through ServerBrowserMenuUI.JoinActions_DirectJoin()
        // → JoinProcess_FindRoomById() → JoinProcess_Init(Room) → JoinProcess_Join().
        // For now, log the intent with full diagnostics.
        ExecuteConnectOrLog();
    }

    //------------------------------------------------------------------------------------------------
    // Saves the config with enabled=false to prevent reboot loops
    void SaveDisabledConfig()
    {
        SCR_JsonSaveContext saveContext = new SCR_JsonSaveContext();
        saveContext.WriteValue("enabled", false);
        saveContext.WriteValue("server_ip", m_sServerIp);
        saveContext.WriteValue("server_port", m_iServerPort);
        saveContext.WriteValue("password", m_sPassword);

        bool saved = saveContext.SaveToFile(CONFIG_PATH);
        string savedStr = "false";
        if (saved)
            savedStr = "true";

        Print("[LLMAutoConnect] Disabled flag saved: " + savedStr);
    }

    //------------------------------------------------------------------------------------------------
    // Connection attempt — currently stubbed with diagnostic logging.
    //
    // VERIFIED APIs available:
    //   BackendApi api = GetGame().GetBackendApi();     // real
    //   ClientLobby lobby = api.GetClientLobby();       // real (returns interface)
    //
    // MISSING (must verify before implementing):
    //   ClientLobby: exact method to find a Room by IP:port (likely FindRoomByIp or similar)
    //   Room: how to construct/reset from (ip, port, password)
    //
    // VANILLA reference flow (from Doxygen functions_j.html):
    //   ServerBrowserMenuUI.JoinActions_DirectJoin()   // the UI "Direct Join" button handler
    //   ServerBrowserMenuUI.JoinProcess_FindRoomById() // finds server by ID
    //   ServerBrowserMenuUI.JoinProcess_OnFindRoomSuccess(Room room)  // callback w/ Room
    //   ServerBrowserMenuUI.JoinProcess_Init(Room room) // init join process
    //   ServerBrowserMenuUI.JoinProcess_Join()         // actual join
    //
    void ExecuteConnectOrLog()
    {
        Print("[LLMAutoConnect] Connect requested for " + m_sServerIp + ":" + m_iServerPort);

        // Verify BackendApi is reachable (real, verified API)
        BackendApi api = GetGame().GetBackendApi();
        if (!api)
        {
            Print("[LLMAutoConnect] ERROR: GetBackendApi() returned null");
            return;
        }

        Print("[LLMAutoConnect] BackendApi acquired OK");

        // Verify authentication status (real, verified method)
        string authStr = "false";
        if (api.IsAuthenticated())
            authStr = "true";

        Print("[LLMAutoConnect] BackendApi authenticated: " + authStr);
        Print("[LLMAutoConnect] TODO: implement real connect via ClientLobby/ServerBrowserMenuUI");
        Print("[LLMAutoConnect] Config will remain disabled until connect is implemented");
    }

    //------------------------------------------------------------------------------------------------
    // Helper: bool to string (avoid fragile bool concat per enforce-script.md skill)
    string BoolStr(bool b)
    {
        if (b)
            return "true";
        return "false";
    }
}
