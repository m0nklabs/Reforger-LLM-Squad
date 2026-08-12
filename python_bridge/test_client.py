"""
Standalone test client for Reforger LLM Bridge.
Tests the bridge WITHOUT Arma Reforger running.
Simulates game SITREP, orders, AI thoughts, Stavka strategic AI, voice handler, and TTS.

Usage:
    python test_client.py          # run all tests
    python test_client.py health   # just health check
    python test_client.py sitrep   # just SITREP test
"""

import json
import time
import sys
import os
import math
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
    print("\n=== Test: Health Check ===")
    try:
        resp = requests.get(f"{BRIDGE_URL}/health", timeout=5)
        data = resp.json()
        print(f"  Status: {data['status']}")
        print(f"  Uptime: {data['uptime_seconds']}s")
        print(f"  LLM calls: {data['llm_calls']}")
        print(f"  SITREPs received: {data['sitreps_received']}")
        print(f"  SITREPs skipped (dedup): {data['sitreps_skipped_llm']}")
        print(f"  Players active: {data.get('players_active', '?')}")
        print(f"  Secs since last SITREP: {data.get('secs_since_last_sitrep', '?')}")
        print(f"  Model: {data['model']}")
        print("[PASS]")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_sitrep_no_enemies():
    """Test /sitrep with no enemies nearby — expect HOLD"""
    print("\n=== Test: SITREP (no enemies) ===")
    payload = {
        "source": "test_client",
        "type": "SITREP",
        "position": [100.0, 0.0, 200.0],
        "squad": [
            {"name": "Alpha_1", "order": "HOLD", "sitrep": "clear"},
            {"name": "Alpha_2", "order": "HOLD", "sitrep": "clear"},
            {"name": "Alpha_3", "order": "HOLD", "sitrep": "clear"},
            {"name": "Alpha_4", "order": "HOLD", "sitrep": "clear"},
        ],
        "enemies": [],
        "enemy_count": 0,
    }
    try:
        resp = requests.get(f"{BRIDGE_URL}/sitrep?data={requests.utils.quote(json.dumps(payload))}", timeout=30)
        data = resp.json()
        action = data.get("action", "UNKNOWN")
        print(f"  Action: {action}")
        print(f"  Voice reply: {data.get('voice_reply', '')}")
        print(f"  Offset: {data.get('target_offset', None)}")
        print("[PASS]")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_sitrep_with_enemies():
    """Test /sitrep with enemies nearby — expect ENGAGE or FLANK"""
    print("\n=== Test: SITREP (enemies detected) ===")
    payload = {
        "source": "test_client",
        "type": "SITREP",
        "position": [100.0, 0.0, 200.0],
        "squad": [
            {"name": "Alpha_1", "order": "HOLD", "sitrep": "enemy contact"},
            {"name": "Alpha_2", "order": "HOLD", "sitrep": "enemy contact"},
            {"name": "Alpha_3", "order": "HOLD", "sitrep": "clear"},
            {"name": "Alpha_4", "order": "HOLD", "sitrep": "clear"},
        ],
        "enemies": [
            {"dx": 250.0, "dz": 0.0, "dist": 250.0},
            {"dx": 180.0, "dz": -100.0, "dist": 206.0},
        ],
        "enemy_count": 2,
    }
    try:
        resp = requests.get(f"{BRIDGE_URL}/sitrep?data={requests.utils.quote(json.dumps(payload))}", timeout=30)
        data = resp.json()
        action = data.get("action", "UNKNOWN")
        print(f"  Action: {action}")
        print(f"  Voice reply: {data.get('voice_reply', '')}")
        print(f"  Offset: {data.get('target_offset', None)}")
        if action in ("ENGAGE", "FLANK", "MOVE", "SUPPRESS"):
            print("[PASS] LLM responded with combat action")
        elif action == "HOLD":
            print("[WARN] LLM chose HOLD despite enemies — may be valid strategy")
        else:
            print(f"[WARN] Unexpected action: {action}")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_orders():
    """Test /orders GET (poll) and POST (queue command)"""
    print("\n=== Test: Orders (poll + queue) ===")
    try:
        cmd = {"cmd": "spawn", "count": 3, "prefab": "us_ar"}
        resp = requests.post(f"{BRIDGE_URL}/orders", json=cmd, timeout=5)
        print(f"  POST /orders: {resp.status_code}")

        resp = requests.get(f"{BRIDGE_URL}/orders", timeout=5)
        data = resp.json()
        orders = data.get("orders", [])
        print(f"  GET /orders: {len(orders)} pending")
        if len(orders) > 0:
            print(f"  First order: {orders[0]}")
        print("[PASS]")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_ai_thought():
    """Test /ai_thought endpoint"""
    print("\n=== Test: AI Thoughts ===")
    try:
        resp = requests.get(f"{BRIDGE_URL}/ai_thought", timeout=30)
        data = resp.json()
        thoughts = data.get("thoughts", [])
        print(f"  Thoughts received: {len(thoughts)}")
        for t in thoughts[:4]:
            print(f"    [{t.get('name', '?')}] {t.get('thought', '')}")
        print("[PASS]")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_stavka():
    """Test /stavka endpoint (OPFOR strategic AI)"""
    print("\n=== Test: Stavka (OPFOR strategic AI) ===")
    try:
        resp = requests.get(f"{BRIDGE_URL}/stavka?opfor=3", timeout=30)
        data = resp.json()
        orders = data.get("orders", [])
        print(f"  Orders: {len(orders)}")
        for o in orders:
            print(f"    {o}")
        print("[PASS]")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_voice():
    """Test /voice endpoint (voice handler status)"""
    print("\n=== Test: Voice Handler ===")
    try:
        resp = requests.get(f"{BRIDGE_URL}/voice", timeout=5)
        data = resp.json()
        print(f"  Enabled: {data.get('enabled', False)}")
        print(f"  PTT key: {data.get('ptt_key', '?')}")
        print(f"  Model: {data.get('model', '?')} (loaded={data.get('model_loaded', False)})")
        print(f"  Running: {data.get('running', False)}")
        if data.get("last_transcription"):
            print(f"  Last: \"{data['last_transcription']}\"")
        print("[PASS]")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_tts():
    """Test TTS handler status."""
    print("\n=== Test: TTS Handler ===")
    try:
        r = requests.get(f"{BRIDGE_URL}/tts", timeout=5)
        if r.status_code == 200:
            data = r.json()
            print(f"  Enabled: {data.get('enabled')}")
            print(f"  Engine: {data.get('engine')}")
            print(f"  edge-tts: {data.get('edge_available')}")
            print(f"  pyttsx3: {data.get('pyttsx3_available')}")
            print(f"  Running: {data.get('running')}")
            if data.get('enabled') and data.get('running'):
                print("[PASS] TTS handler active")
                return True
            else:
                print("[WARN] TTS not enabled/running")
                return True  # soft pass - TTS is optional
        else:
            print(f"[FAIL] Status: {r.status_code}")
            return False
    except Exception as e:
        print(f"[FAIL] {e}")
        return False

def test_status():
    """Test /status GET (dashboard live view — regressed once: 500 when
    app_state held the chatter asyncio.Task, rule 84). Pure GET, no LLM."""
    print("\n=== Test: Status (dashboard live view) ===")
    try:
        resp = requests.get(f"{BRIDGE_URL}/status", timeout=5)
        data = resp.json()
        state = data.get("state", {})
        print(f"  HTTP {resp.status_code}, state keys: {len(state)}")
        print(f"  battle_log: {len(state.get('battle_log', []))} entries")
        print(f"  last_leader_state: {state.get('last_leader_state', '?')}")
        print(f"  last_sitrep: {data.get('last_sitrep')}")
        if resp.status_code == 200 and "battle_log" in state and "last_leader_state" in state:
            print("[PASS] /status returns the dashboard live view")
            return True
        print("[FAIL] /status shape unexpected")
        return False
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_suggestions():
    """Test /suggestions GET (C.5 CO approval panel). Pure GET, no LLM."""
    print("\n=== Test: Suggestions (CO approval panel) ===")
    try:
        resp = requests.get(f"{BRIDGE_URL}/suggestions", timeout=5)
        data = resp.json()
        sugs = data.get("suggestions", [])
        print(f"  HTTP {resp.status_code}, suggestions: {len(sugs)}")
        if resp.status_code == 200 and isinstance(sugs, list):
            print("[PASS] /suggestions returns the suggestion list")
            return True
        print("[FAIL] /suggestions shape unexpected")
        return False
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_latency():
    """Measure end-to-end latency for SITREP -> LLM -> response"""
    print("\n=== Test: Latency ===")
    payload = {
        "source": "test_client",
        "type": "SITREP",
        "position": [500.0, 0.0, 500.0],
        "squad": [
            {"name": "Bravo_1", "order": "HOLD", "sitrep": "patrol"},
            {"name": "Bravo_2", "order": "HOLD", "sitrep": "patrol"},
        ],
        "enemies": [],
        "enemy_count": 0,
    }
    latencies = []
    for i in range(3):
        payload["position"][0] = 500.0 + i * 100
        start = time.time()
        try:
            resp = requests.get(
                f"{BRIDGE_URL}/sitrep?data={requests.utils.quote(json.dumps(payload))}",
                timeout=30,
            )
            latency = (time.time() - start) * 1000
            latencies.append(latency)
            print(f"  Call {i+1}: {latency:.0f}ms")
        except Exception as e:
            print(f"  Call {i+1}: FAILED — {e}")

    if latencies:
        avg = sum(latencies) / len(latencies)
        print(f"  Average: {avg:.0f}ms")
        if avg < 1500:
            print("[PASS] Good latency (<1.5s)")
        else:
            print(f"[WARN] Latency {avg:.0f}ms — slow model?")
        return True
    return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("  Reforger LLM Bridge — Test Suite")
    print("=" * 60)
    print(f"  Bridge: {BRIDGE_URL}")
    print(f"  Model:  {CONFIG['llm']['model']}")
    print(f"  Proxy:  {CONFIG['llm']['base_url']}")

    # Allow selective test execution
    if len(sys.argv) > 1 and sys.argv[1] != "all":
        test_name = sys.argv[1]
        test_map = {
            "health": test_health,
            "sitrep": test_sitrep_no_enemies,
            "enemy": test_sitrep_with_enemies,
            "orders": test_orders,
            "thought": test_ai_thought,
            "stavka": test_stavka,
            "voice": test_voice,
            "tts": test_tts,
            "status": test_status,
            "suggestions": test_suggestions,
            "latency": test_latency,
        }
        if test_name in test_map:
            test_map[test_name]()
            return
        else:
            print(f"Unknown test: {test_name}. Available: {', '.join(test_map.keys())}")
            return

    # Run all tests
    results = []
    results.append(("Health", test_health()))
    results.append(("SITREP (no enemies)", test_sitrep_no_enemies()))
    results.append(("SITREP (with enemies)", test_sitrep_with_enemies()))
    results.append(("Orders", test_orders()))
    results.append(("AI Thoughts", test_ai_thought()))
    results.append(("Stavka", test_stavka()))
    results.append(("Voice", test_voice()))
    results.append(("TTS", test_tts()))
    results.append(("Status", test_status()))
    results.append(("Suggestions", test_suggestions()))
    results.append(("Latency", test_latency()))

    # Summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, r in results if r)
    for name, r in results:
        print(f"  {'[PASS]' if r else '[FAIL]'} — {name}")
    print(f"\n  {passed}/{len(results)} passed")
    if passed == len(results):
        print("  [OK] All tests passed!")
    elif passed > 0:
        print("  [WARN] Some tests failed.")
    else:
        print("  [FAIL] All tests failed — is the bridge running?")


if __name__ == "__main__":
    main()
