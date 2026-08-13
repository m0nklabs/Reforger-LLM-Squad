// SCR_BaseGameMode_Component.c - Component to wire LLMBridge + AutoConnect into the game
// Phase 1.2: Component wiring
// Phase 1.x: Auto-connect to dedicated server via profile JSON ($profile:agent_auto_connect.json)
//
// Pattern from SampleMod_ModdedScript: use 'modded class' to extend existing classes
// This extends SCR_BaseGameMode to instantiate LLMBridge and call Update periodically
//
// Fixes from previous compile attempts:
// - Simplified: removed custom component class, use direct modded class approach
// - Using ref for member variables pointing to user-created classes (LLMBridge)
// - No override keyword on methods that don't exist in base class
// - Renamed Update -> PeriodicUpdate to avoid callback overload conflicts

//------------------------------------------------------------------------------------------------
// Extend SCR_BaseGameMode to add LLM functionality
// This is the main wiring point - when a scenario starts, OnGameStart is called
modded class SCR_BaseGameMode
{
    ref LLMBridge m_pLLMBridge;
    bool m_bLLMInitialized;
    float m_fGameTime;

    // Auto-connect component
    ref LLMAutoConnect m_pAutoConnect;

    // F3.1: Stavka OPFOR strategic AI
    ref StavkaController m_pStavka;

    // Player presence tracking — pause LLM when no human players
    bool m_bNoPlayerMode;

    //------------------------------------------------------------------------------------------------
    override void EOnInit(IEntity owner)
    {
        super.EOnInit(owner);
        Print("[LLMGameMode] EOnInit FIRED — modded SCR_BaseGameMode is alive");
    }

    //------------------------------------------------------------------------------------------------
    override void OnGameStart()
    {
        // CRITICAL: the bridge client (LLMBridge/Stavka/thoughts/orders) must run
        // ONLY on the dedicated server. Without this guard the game CLIENT also
        // starts LLMBridge, polls /orders and /ai_thought against the same bridge,
        // steals orders from the DS ("No AI group found") and sends duplicate SITREPs.
        if (!Replication.IsServer())
        {
            Print("[LLMGameMode] Client — bridge client disabled (DS-only mod)");
            return;
        }

        Print("[LLMGameMode] OnGameStart - Initializing LLM Bridge");
        if (m_bLLMInitialized)
            return;
        
        m_bLLMInitialized = true;
        
        // Create the LLMBridge instance (ref ensures proper ownership)
        m_pLLMBridge = new LLMBridge();
        if (m_pLLMBridge)
        {
            m_pLLMBridge.Activate();
            
            // Start periodic Update() calls via Callqueue (every 1 second = 1000ms)
            // Timeslice is in seconds (1.0 = 1 second per update)
            GetGame().GetCallqueue().CallLater(PeriodicUpdate, 1000, true, 1.0);
            
            Print("[LLMGameMode] LLM Bridge activated, periodic updates started");
        }
        else
        {
            Print("[LLMGameMode] ERROR: Failed to create LLMBridge instance");
        }

        // F3.1: Stavka OPFOR strategic AI — strategic cycle every 60s
        m_pStavka = new StavkaController("http://127.0.0.1:5001");
        Print("[LLMGameMode] Stavka controller initialized");

        // --- Auto-connect hook (F1.x: auto server connection via profile JSON) ---
        // Delayed to let BackendApi / authentication initialize before we call GetBackendApi()
        m_pAutoConnect = new LLMAutoConnect();
        GetGame().GetCallqueue().CallLater(DeferredAutoConnect, 3000, false);
        Print("[LLMGameMode] Auto-connect scheduled (3s delay)");
    }

    //------------------------------------------------------------------------------------------------
    void PeriodicUpdate(float timeslice)
    {
        // Check if any human player is connected (scan player IDs 1-32)
        bool hasPlayer = false;
        PlayerManager pm = GetGame().GetPlayerManager();
        if (pm)
        {
            for (int i = 1; i <= 32; i++)
            {
                if (pm.GetPlayerControlledEntity(i))
                {
                    hasPlayer = true;
                    break;
                }
            }
        }

        if (!hasPlayer)
        {
            // No human player — skip all LLM activity to save resources
            if (!m_bNoPlayerMode)
            {
                m_bNoPlayerMode = true;
                Print("[LLMGameMode] No human players detected — pausing all LLM activity");
            }
            return;
        }

        if (m_bNoPlayerMode)
        {
            m_bNoPlayerMode = false;
            Print("[LLMGameMode] Player detected — resuming LLM activity");
        }

        if (!m_pLLMBridge)
            return;
        
        // Update the game time accumulator
        m_fGameTime += timeslice;
        
        // Update the LLMBridge - This handles SITREP collection, waypoint checks, etc.
        m_pLLMBridge.Update(timeslice);

        // F3.1: Update Stavka controller (OPFOR strategic AI)
        if (m_pStavka)
            m_pStavka.Update(timeslice);
    }

    //------------------------------------------------------------------------------------------------
    void DeferredAutoConnect()
    {
        if (m_pAutoConnect)
        {
            Print("[LLMGameMode] Deferred auto-connect starting...");
            m_pAutoConnect.CheckAndConnect();
        }
        else
        {
            Print("[LLMGameMode] ERROR: m_pAutoConnect is null in DeferredAutoConnect");
        }
    }

    //------------------------------------------------------------------------------------------------
    override void OnGameEnd()
    {
        Print("[LLMGameMode] OnGameEnd - Shutting down LLM Bridge");
        
        // Stop periodic updates
        GetGame().GetCallqueue().Remove(PeriodicUpdate);
        GetGame().GetCallqueue().Remove(DeferredAutoConnect);
        
        if (m_pLLMBridge)
        {
            m_pLLMBridge = null;
        }

        if (m_pStavka)
        {
            m_pStavka = null;
        }

        if (m_pAutoConnect)
        {
            m_pAutoConnect = null;
        }
        
        m_bLLMInitialized = false;
    }
};