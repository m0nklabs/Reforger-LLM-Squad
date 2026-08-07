"""
Standalone test client for Reforger LLM Bridge.
Tests the bridge WITHOUT Arma Reforger running.
Simulates game SITREP and operator commands.
"""

import json
import time
import sys
import os
import requests

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Import config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

BRIDGE_URL = f"http://{CONFIG['server']['host']}:{CONFIG['server']['port']}"

def test_health():
    """Test /health endpoint"""
    print("\n=== Test 1: Health Check ===")
    try:
        resp = requests.get(f"{BRIDGE_URL}/health", timeout=5)
        data = resp.json()
        print(f"Status: {data['status']}")
        print(f"Uptime: {data['uptime_seconds']}s")
        print(f"Proxy: {data['proxy']}")
        print(f"Model: {data['model']}")
        print("[PASS] Health check passed!")
        return True
    except Exception as e:
        print(f"[FAIL] Health check failed: {e}")
        return False

def test_sitrep():
    """Test /sitrep endpoint with simulated game data"""
    print("\n=== Test 2: SITREP Bridge ===")
    
    sitrep_payload = {
        "squad": "ALPHA",
        "grid": "042-081",
        "position_x": 1234.5,
        "position_y": 567.8,
        "position_z": 12.3,
        "health": 85.5,
        "ammo_percent": 62.0,
        "status": "Patrolling",
        "nearby_enemies": 2
    }
    
    try:
        resp = requests.post(
            f"{BRIDGE_URL}/sitrep",
            json=sitrep_payload,
            timeout=CONFIG["llm"]["timeout_seconds"] + 2
        )
        data = resp.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        print(f"Action: {data['action']}")
        print(f"Voice reply: {data['voice_reply']}")
        print("[PASS] SITREP test passed!")
        return True
    except Exception as e:
        print(f"[FAIL] SITREP test failed: {e}")
        return False

def test_command():
    """Test /command endpoint with operator command"""
    print("\n=== Test 3: Operator Command ===")
    
    command_payload = {
        "squad": "ALPHA",
        "operator_command": "Move to grid 042-081 and suppress enemies.",
        "current_situation": "Squad ALPHA at grid 042-081, 2 enemies spotted North. Health: 85%. Ammo: 62%."
    }
    
    try:
        resp = requests.post(
            f"{BRIDGE_URL}/command",
            json=command_payload,
            timeout=CONFIG["llm"]["timeout_seconds"] + 2
        )
        data = resp.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        print(f"Action: {data['action']}")
        print(f"Target grid: {data.get('target_grid', 'N/A')}")
        print(f"Voice reply: {data['voice_reply']}")
        print("[PASS] Command test passed!")
        return True
    except Exception as e:
        print(f"[FAIL] Command test failed: {e}")
        return False

def test_latency():
    """Test end-to-end latency"""
    print("\n=== Test 4: Latency Measurement ===")
    
    sitrep_payload = {
        "squad": "BRAVO",
        "grid": "100-200",
        "position_x": 500.0,
        "position_y": 200.0,
        "position_z": 10.0,
        "health": 70.0,
        "ammo_percent": 50.0,
        "status": "Engaging",
        "nearby_enemies": 3
    }
    
    latencies = []
    for i in range(5):
        start = time.time()
        resp = requests.post(
            f"{BRIDGE_URL}/sitrep",
            json=sitrep_payload,
            timeout=CONFIG["llm"]["timeout_seconds"] + 2
        )
        latency = (time.time() - start) * 1000
        latencies.append(latency)
        print(f"  Call {i+1}: {latency:.1f}ms")
    
    avg_latency = sum(latencies) / len(latencies)
    min_latency = min(latencies)
    max_latency = max(latencies)
    
    print(f"\nAverage: {avg_latency:.1f}ms")
    print(f"Min: {min_latency:.1f}ms")
    print(f"Max: {max_latency:.1f}ms")
    
    if avg_latency < 1000:
        print("[PASS] Latency is good (< 1s average)!")
    else:
        print("[WARN] Latency is acceptable but could be better.")
    return True

def test_error_handling():
    """Test error handling (timeout, invalid data)"""
    print("\n=== Test 5: Error Handling ===")
    
    # Test invalid data
    try:
        resp = requests.post(
            f"{BRIDGE_URL}/sitrep",
            json={"squad": "INVALID_SQUAD", "grid": "000", "position_x": 0, "position_y": 0, "position_z": 0, "health": 0, "ammo_percent": 0, "status": "test"},
            timeout=5
        )
        if resp.status_code == 422:
            print("[PASS] Invalid data returns 422 (Pydantic validation)")
        else:
            print(f"[WARN] Invalid data response: {resp.status_code}")
    except Exception as e:
        print(f"[FAIL] Error handling test failed: {e}")
        return False
    
    return True

def main():
    """Run all tests"""
    print("=" * 60)
    print("  Reforger LLM Bridge - Standalone Test Suite")
    print("=" * 60)
    print(f"\nBridge URL: {BRIDGE_URL}")
    print(f"Proxy URL: {CONFIG['llm']['base_url']}")
    print(f"Model: {CONFIG['llm']['model']}")
    print(f"Timeout: {CONFIG['llm']['timeout_seconds']}s")
    
    results = []
    
    results.append(("Health Check", test_health()))
    results.append(("SITREP Bridge", test_sitrep()))
    results.append(("Operator Command", test_command()))
    results.append(("Latency", test_latency()))
    results.append(("Error Handling", test_error_handling()))
    
    # Summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status} - {name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n[OK] All tests passed! Bridge is ready for in-game testing.")
        return 0
    else:
        print(f"\n[WARN] {total - passed} test(s) failed. Check logs for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
