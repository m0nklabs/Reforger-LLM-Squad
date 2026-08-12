"""Unit tests for the /status JSON-safe state view + /soldiers drift guard.

Regression: C.2 put an asyncio.Task (chatter_task) into app_state. GET /status
dumped the raw app_state dict, jsonable_encoder crashed on the Task and the
endpoint returned 500 - which silently killed the dashboard's battle log /
thoughts / tactical map (pollStatus swallows fetch errors).

Covers:
- /status returns 200 with a REAL asyncio.Task in app_state["chatter_task"]
- chatter_task is absent from the response state
- dashboard fields (battle_log, cached_thoughts, last_leader_state) survive
- future-proofing: an arbitrary non-JSON value is dropped, not fatal
- /soldiers does not 500 on bare-string relationship entries / non-dict
  opinions in old memory files (drift guard parity with get_social_summary)

Usage:  python_bridge\venv\Scripts\python.exe python_bridge\test_status_guard.py
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import main as bridge  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


def make_task():
    """A real asyncio.Task WITHOUT a running loop (jsonable_encoder crashes on it)."""
    loop = asyncio.new_event_loop()
    task = loop.create_task(asyncio.sleep(1))
    return task, loop


def main():
    print("status-guard tests (/status 500 regression + /soldiers drift guard)")
    client = TestClient(bridge.app)  # no context manager: no startup events

    tmp = Path(tempfile.mkdtemp(prefix="status_guard_"))
    old_dirs = (bridge.SOLDIER_MEMORY_DIR, bridge.SOLDIER_GRAVEYARD_DIR)
    bridge.SOLDIER_MEMORY_DIR = tmp / "ai_soldiers"
    bridge.SOLDIER_GRAVEYARD_DIR = bridge.SOLDIER_MEMORY_DIR / "graveyard"
    bridge.SOLDIER_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    bridge.SOLDIER_GRAVEYARD_DIR.mkdir(exist_ok=True)
    old_state_items = dict(bridge.app_state)
    try:
        # ── 1. /status 200 with a live chatter Task in app_state ───────
        task, loop = make_task()
        try:
            bridge.app_state["chatter_task"] = task
            r = client.get("/status")
            check("/status returns 200 with chatter_task set", r.status_code == 200, f"HTTP {r.status_code}")
            state = r.json().get("state", {})
            check("chatter_task absent from state", "chatter_task" not in state)
            check("last_sitrep present", "last_sitrep" in r.json())
            check("dashboard battle_log field present", "battle_log" in state)
            check("dashboard cached_thoughts field present", "cached_thoughts" in state)
            check("dashboard last_leader_state field present", "last_leader_state" in state)
        finally:
            task.cancel()
            loop.close()

        # ── 2. Future-proofing: unknown non-JSON value is dropped ──────
        class WeirdHandle:
            __slots__ = ()  # no __dict__ -> jsonable_encoder raises

        bridge.app_state["some_weird_handle"] = WeirdHandle()
        r = client.get("/status")
        check("/status 200 with unknown non-JSON value", r.status_code == 200, f"HTTP {r.status_code}")
        check("weird handle dropped from state", "some_weird_handle" not in r.json().get("state", {}))
        del bridge.app_state["some_weird_handle"]

        # ── 3. /soldiers drift guard: bare-string relationships ────────
        mem = {
            "name": "Alpha_1",
            "status": "alive",
            "relationships": {"Alpha_2": "trusted", "Alpha_3": {"score": 5, "label": "trusted"}},
            "opinions": ["legacy bare string", {"topic": "Alpha_2", "opinion": "solid"}],
        }
        (bridge.SOLDIER_MEMORY_DIR / "Alpha_1.json").write_text(
            json.dumps(mem), encoding="utf-8"
        )
        r = client.get("/soldiers")
        check("/soldiers 200 with drifted memory file", r.status_code == 200, f"HTTP {r.status_code}")
        soldiers = r.json().get("soldiers", [])
        alpha1 = next((s for s in soldiers if s.get("name") == "Alpha_1"), None)
        check("soldier listed despite drift", alpha1 is not None)
        rels = (alpha1 or {}).get("relationships", {})
        check("bare-string relationship filtered", rels == {"Alpha_3": "trusted"}, str(rels))
        ops = (alpha1 or {}).get("opinions", [])
        check("non-dict opinion filtered", ops == ["solid"], str(ops))
    finally:
        bridge.SOLDIER_MEMORY_DIR, bridge.SOLDIER_GRAVEYARD_DIR = old_dirs
        bridge.app_state.clear()
        bridge.app_state.update(old_state_items)
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} test(s): {FAILURES}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
