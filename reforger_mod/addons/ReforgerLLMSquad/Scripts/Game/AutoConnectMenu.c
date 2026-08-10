// AutoConnectMenu.c - F1.x: Auto-connect to dedicated server
//
// Implements the REAL auto-connect using verified Doxygen APIs:
//   ServerBrowserMenuUI.JoinActions_DirectJoin(string params, EDirectJoinFormats format, bool publicNetwork)
//   ServerBrowserMenuUI.TryOpenServerBrowser()
//   ServerBrowserMenuUI.OnMenuOpen() - override hook
//   SCR_MainMenuEntity.EOnFrame() - periodic check hook
//
// File source: Game/UI/Menu/ServerBrowserMenuUI.c (from Doxygen)
// All methods verified against ArmaReforgerScriptAPIPublic.zip

//------------------------------------------------------------------------------------------------
// Modded server browser menu - intercepts OnMenuOpen to trigger auto-connect
modded class ServerBrowserMenuUI
{
	override void OnMenuOpen()
	{
		super.OnMenuOpen();

		// Check if auto-connect config exists and is enabled
		if (!FileIO.FileExists("$profile:agent_auto_connect.json"))
			return;

		JsonLoadContext loadCtx = new JsonLoadContext();
		if (!loadCtx.LoadFromFile("$profile:agent_auto_connect.json"))
			return;

		bool enabled = false;
		loadCtx.ReadValue("enabled", enabled);
		if (!enabled)
			return;

		string serverIp = "127.0.0.1";
		int serverPort = 2001;
		loadCtx.ReadValue("server_ip", serverIp);
		loadCtx.ReadValue("server_port", serverPort);

		Print("[AutoConnect] Server browser opened, triggering direct join to " + serverIp + ":" + serverPort);

		// Self-disable config to prevent loops
		JsonSaveContext saveCtx = new JsonSaveContext();
		saveCtx.WriteValue("enabled", false);
		saveCtx.WriteValue("server_ip", serverIp);
		saveCtx.WriteValue("server_port", serverPort);
		saveCtx.SaveToFile("$profile:agent_auto_connect.json");

		// Trigger direct join - JoinActions_DirectJoin is protected, accessible from modded class
		// The params string is "ip:port", format is EDirectJoinFormats (0 = IP format)
		string connectParams = serverIp + ":" + serverPort;
		JoinActions_DirectJoin(connectParams, 0, true);
		Print("[AutoConnect] DirectJoin called with params=" + connectParams);
	}
}

//------------------------------------------------------------------------------------------------
// Modded main menu entity - triggers auto-connect when main menu loads
modded class SCR_MainMenuEntity
{
	bool m_bAutoConnectChecked = false;

	override void EOnFrame(IEntity owner, float timeSlice)
	{
		if (m_bAutoConnectChecked)
			return;
		m_bAutoConnectChecked = true;

		// Check if auto-connect config exists and is enabled
		if (!FileIO.FileExists("$profile:agent_auto_connect.json"))
			return;

		JsonLoadContext loadCtx = new JsonLoadContext();
		if (!loadCtx.LoadFromFile("$profile:agent_auto_connect.json"))
			return;

		bool enabled = false;
		loadCtx.ReadValue("enabled", enabled);
		if (!enabled)
			return;

		Print("[AutoConnect] Main menu loaded, auto-connect enabled - opening server browser");

		// Open the server browser - our modded OnMenuOpen() will trigger the direct join
		// Use CallLater to ensure the menu system is fully initialized
		GetGame().GetCallqueue().CallLater(AutoOpenServerBrowser, 2000);
	}

	void AutoOpenServerBrowser()
	{
		ServerBrowserMenuUI.TryOpenServerBrowser();
		Print("[AutoConnect] TryOpenServerBrowser() called from main menu");
	}
}
