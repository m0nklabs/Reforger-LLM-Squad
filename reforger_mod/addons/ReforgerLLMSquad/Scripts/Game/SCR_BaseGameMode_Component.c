// SCR_BaseGameMode_Component.c - Component to wire LLMBridge into the game
// Phase 1.2: Component wiring
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

    //------------------------------------------------------------------------------------------------
    override void OnGameStart()
    {
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
    }

    //------------------------------------------------------------------------------------------------
    void PeriodicUpdate(float timeslice)
    {
        if (!m_pLLMBridge)
            return;
        
        // Update the game time accumulator
        m_fGameTime += timeslice;
        
        // Update the LLMBridge - This handles SITREP collection, waypoint checks, etc.
        m_pLLMBridge.Update(timeslice);
    }

    //------------------------------------------------------------------------------------------------
    override void OnGameEnd()
    {
        Print("[LLMGameMode] OnGameEnd - Shutting down LLM Bridge");
        
        // Stop periodic updates
        GetGame().GetCallqueue().Remove(PeriodicUpdate);
        
        if (m_pLLMBridge)
        {
            m_pLLMBridge = null;
        }
        
        m_bLLMInitialized = false;
    }
};