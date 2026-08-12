"""Unit tests for C.2 radio chatter layer (no live LLM / no TTS audio needed).

Runs offline. The gating rules live in the pure function _chatter_due() —
everything else (line picking, battle-log age parsing) is tested directly.
No audio is produced: tts_handler.speak is never invoked by these tests.

Tests:
- _chatter_due gates: tts disabled / no session / not yet / orders pending /
  recent battle event / quiet-and-due
- _battle_event_age_seconds: fresh vs old events, malformed entries
- _chatter_member picks from the last SITREP's ALIVE members only
- _chatter_line formats the speaker name for TTS
- voice index is stable per member name

Usage:  python_bridge\venv\Scripts\python.exe python_bridge\test_chatter.py
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import main as bridge  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


def log_entry(seconds_ago, kind="CONTACT"):
    ts = time.strftime("%H:%M:%S", time.localtime(time.time() - seconds_ago))
    return f"[{ts}] {kind}: test event"


def make_sitrep(names, alive=None):
    alive = alive if alive is not None else [True] * len(names)
    return bridge.SitRepRequest(squad=[
        bridge.SitRepMember(name=n, alive=a) for n, a in zip(names, alive)
    ])


def main():
    print("C.2 radio chatter tests")
    saved = {
        "tts_enabled": bridge.tts_handler.enabled,
        "last_sitrep_time": bridge.app_state.get("last_sitrep_time"),
        "last_sitrep": bridge.app_state.get("last_sitrep"),
        "chatter_next_at": bridge.app_state.get("chatter_next_at"),
        "pending_orders": bridge.app_state.get("pending_orders"),
        "battle_log": bridge.app_state.get("battle_log"),
    }
    bridge.tts_handler.enabled = True
    bridge.app_state["last_sitrep_time"] = time.time()  # session active
    bridge.app_state["chatter_next_at"] = 0.0           # due
    bridge.app_state["pending_orders"] = []
    bridge.app_state["battle_log"] = []
    try:
        # ── _battle_event_age_seconds ─────────────────────────────────
        age = bridge._battle_event_age_seconds(log_entry(5))
        check("fresh event age ~5s", 3 < age < 8, f"{age:.1f}s")
        age = bridge._battle_event_age_seconds(log_entry(600))
        check("old event age ~600s", 590 < age < 610, f"{age:.1f}s")
        age = bridge._battle_event_age_seconds("no timestamp here")
        check("malformed entry age 0", age == 0.0, f"{age}")

        # ── _chatter_due gating ───────────────────────────────────────
        due, reason = bridge._chatter_due()
        check("due when session active + quiet", due and reason == "quiet", reason)

        bridge.tts_handler.enabled = False
        due, reason = bridge._chatter_due()
        check("gated: tts disabled", not due and reason == "tts_disabled", reason)
        bridge.tts_handler.enabled = True

        bridge.app_state["last_sitrep_time"] = time.time() - 200
        due, reason = bridge._chatter_due()
        check("gated: no session", not due and reason == "no_session", reason)
        bridge.app_state["last_sitrep_time"] = time.time()

        bridge.app_state["chatter_next_at"] = time.time() + 60
        due, reason = bridge._chatter_due()
        check("gated: not yet (interval)", not due and reason == "not_yet", reason)
        bridge.app_state["chatter_next_at"] = 0.0

        bridge.app_state["pending_orders"] = [{"cmd": "move", "offset": [50, 0]}]
        due, reason = bridge._chatter_due()
        check("gated: orders pending", not due and reason == "orders_pending", reason)
        bridge.app_state["pending_orders"] = []

        bridge.app_state["battle_log"] = [log_entry(5)]
        due, reason = bridge._chatter_due()
        check("gated: recent battle", not due and reason == "recent_battle", reason)

        bridge.app_state["battle_log"] = [log_entry(600)]
        due, reason = bridge._chatter_due()
        check("due: battle event is old", due and reason == "quiet", reason)

        bridge.app_state["battle_log"] = [log_entry(600, kind="ORDER"), log_entry(10, kind="CRITICAL")]
        due, reason = bridge._chatter_due()
        check("gated: recent CRITICAL", not due and reason == "recent_battle", reason)
        bridge.app_state["battle_log"] = []

        # ── member + line selection ───────────────────────────────────
        sitrep = make_sitrep(["Alpha_1", "Alpha_2", "Alpha_3", "Alpha_4"],
                             alive=[True, True, True, False])
        bridge.app_state["last_sitrep"] = sitrep
        seen = set()
        for _ in range(50):
            line, name = bridge._chatter_line()
            check("line contains spoken name", name.replace("_", " ") in line, line[:50])
            check("member from squad", name in ("Alpha_1", "Alpha_2", "Alpha_3"))
            seen.add(name)
        check("both alive members can be picked", len(seen) >= 2, str(seen))
        check("dead member never picked", "Alpha_4" not in seen)

        # voice index stable per name, in range
        for name in ("Alpha_1", "Alpha_2", "Alpha_3"):
            idx = bridge._name_hash(name, "voice") % 10
            check(f"voice index in range for {name}", 0 <= idx < 10, str(idx))
        check("voice index stable",
              bridge._name_hash("Alpha_1", "voice") % 10 == bridge._name_hash("Alpha_1", "voice") % 10)
    finally:
        bridge.tts_handler.enabled = saved["tts_enabled"]
        for k, v in saved.items():
            if k == "tts_enabled":
                continue
            bridge.app_state[k] = v

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} test(s): {FAILURES}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
