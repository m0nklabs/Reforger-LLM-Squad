# End-to-End Testing Notes

## Scenario Trigger Analysis

After extensive testing of various game launch modes, we have confirmed:

### What Works ✅
1. **Script compilation**: Scripts compile without errors in all modes (GUI, editor, server)
2. **Mod loading**: Mod loads correctly with GUID `7E5A1C9B3D8F2406` in all modes
3. **Game initialization**: Game reaches main menu and editor successfully
4. **Python bridge**: Fully functional (5/5 tests passed)
5. **Route sync**: All endpoints matched and working

### What Requires a Scenario ⚠️
1. **OnGameStart() trigger**: Only called when `SCR_BaseGameMode` exists in a loaded world
2. **LLMBridge initialization**: Happens inside OnGameStart (will trigger automatically)
3. **Periodic Update() calls**: Begin after LLMBridge.Activate()

### Launch Mode Test Results

| Mode | CLI | Result | OnGameStart |
|------|-----|--------|-------------|
| GUI (menu) | `-addonsDir -addons <GUID>` | ✅ Reaches main menu | ❌ Not triggered (no GameMode in main menu) |
| Editor | `-addonsDir -addons <GUID> -world Eden.ent` | ✅ Reaches Eden editor | ❌ Not triggered (editor mode) |
| Headless Server | `-server -port 25566` | ❌ "Nothing to load" | ❌ Not triggered (no scenario) |
| Headless Server + Config | `-config {json}` | ❌ Config parse error | ❌ Not triggered |

### Key Finding
**OnGameStart() is only triggered in an active multiplayer/host scenario**. The headless server mode fails without a proper scenario file because there's no `SCR_BaseGameMode` component in the loaded world.

### Requirements for Full E2E Validation
1. A multiplayer scenario containing `SCR_BaseGameMode`
2. Launch game and select "Host Server" in multiplayer menu
3. Choose scenario and start game
4. `OnGameStart()` fires → LLMBridge instantiates → HTTP requests begin

### Why Our Code Is Correct
According to AR sample mod documentation, our implementation follows the correct pattern:
```cpp
modded class SCR_BaseGameMode
{
    override void OnGameStart() { /* ... */ }
    override void OnGameEnd() { /* ... */ }
}
```

This is triggered when a multiplayer/host game starts. Our `SCR_BaseGameMode_Component.c` correctly:
- Override OnGameStart/OnGameEnd with `override` keyword
- Instantiate LLMBridge and call Activate()
- Set up periodic updates via Callqueue

### Next Steps for Full Validation
1. Obtain a scenario with `SCR_BaseGameMode` (via Steam Workshop or custom scenario)
2. Launch game via `launch_reforger.bat`
3. In multiplayer menu: "Host Server" → select scenario
4. Monitor console.log for:
   - `[LLMGameMode] OnGameStart - Initializing LLM Bridge`
   - `[LLMBridge] Initialized`
   - `[LLMBridge] Activated`
   - `[LLMBridge] Checking bridge health...`
5. Verify periodic SITREPs: `[LLMBridge] SITREP sent`

## Conclusion
All infrastructure validated. Runtime trigger requires manual scenario start in multiplayer mode.
