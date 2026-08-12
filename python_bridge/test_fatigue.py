"""Unit tests for B.4 fatigue & session memory (no live LLM needed).

Runs offline against tmp dirs (real ai_soldiers/reports are NOT touched):
- fatigue level transitions by elapsed session time
- combat acceleration (CRITICAL/CONTACT events push fatigue up)
- mood drift: rested moods degrade at high fatigue, event moods (nervous) stay
- session-end persistence: last_summary.json + per-soldier previous_deployments
- dedup: repeated report writes do not duplicate deployment entries
- _load_last_report_summary restores the recap (bridge restart survival)
- get_situation_text includes the fatigue line

Usage:  python_bridge\venv\Scripts\python.exe python_bridge\test_fatigue.py
"""

import json
import shutil
import sys
import tempfile
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


def make_member(name, alive=True):
    return bridge.SitRepMember(name=name, alive=alive)


def make_sitrep(names):
    return bridge.SitRepRequest(squad=[make_member(n) for n in names])


def set_session(minutes_ago):
    bridge.app_state["session_start_time"] = time.time() - minutes_ago * 60


def write_soldier(name, **fields):
    mem = {"name": name, "status": "alive", **fields}
    bridge.SOLDIER_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    p = bridge.SOLDIER_MEMORY_DIR / f"{name}.json"
    p.write_text(json.dumps(mem, ensure_ascii=False), encoding="utf-8")
    return mem


def read_soldier(name):
    p = bridge.SOLDIER_MEMORY_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    print("B.4 fatigue & session memory tests")
    tmp = Path(tempfile.mkdtemp(prefix="b4_fatigue_"))
    old_dirs = (bridge.SOLDIER_MEMORY_DIR, bridge.SOLDIER_GRAVEYARD_DIR, bridge.REPORTS_DIR)
    bridge.SOLDIER_MEMORY_DIR = tmp / "ai_soldiers"
    bridge.SOLDIER_GRAVEYARD_DIR = bridge.SOLDIER_MEMORY_DIR / "graveyard"
    bridge.REPORTS_DIR = tmp / "reports"
    old_battle_log = bridge.app_state.get("battle_log", [])
    old_session_start = bridge.app_state.get("session_start_time")
    bridge.app_state["battle_log"] = []
    try:
        # ── 1. Level transitions by elapsed time ────────────────────────
        set_session(5)
        f = bridge._compute_fatigue()
        check("fresh under tired_minutes", f["level"] == 0 and f["label"] == "fresh", f"{f}")

        set_session(30)
        f = bridge._compute_fatigue()
        check("tired at 30 min", f["level"] == 1 and f["label"] == "tired", f"{f}")

        set_session(60)
        f = bridge._compute_fatigue()
        check("exhausted at 60 min", f["level"] == 2 and f["label"] == "exhausted", f"{f}")

        set_session(90)
        f = bridge._compute_fatigue()
        check("combat-worn at 90 min", f["level"] == 3 and f["label"] == "combat-worn", f"{f}")

        # ── 2. Combat acceleration ─────────────────────────────────────
        set_session(10)  # would be fresh on time alone
        bridge.app_state["battle_log"] = [
            "[00:00:01] CRITICAL: Squad leader is DOWN!",
            "[00:00:02] CRITICAL: Squad leader is DOWN!",
            "[00:00:03] CRITICAL: Squad leader is DOWN!",
        ]
        f = bridge._compute_fatigue()
        check("CRITICAL x3 accelerates 10-min session to tired", f["level"] == 1, f"{f}")
        bridge.app_state["battle_log"] = []

        # ── 3. update_soldier_fatigue: persistence + mood drift ────────
        write_soldier("Alpha_1", mood="calm")
        set_session(50)  # exhausted (level 2)
        bridge.update_soldier_fatigue([make_member("Alpha_1")])
        mem = read_soldier("Alpha_1")
        check("fatigue persisted to memory file", mem.get("fatigue", {}).get("label") == "exhausted", str(mem.get("fatigue")))
        check("rested mood drifted to tired", mem.get("mood") == "tired", f"mood={mem.get('mood')}")

        # event mood survives: nervous stays nervous at level 3
        write_soldier("Alpha_2", mood="nervous")
        set_session(95)  # combat-worn (level 3)
        bridge.update_soldier_fatigue([make_member("Alpha_2")])
        mem = read_soldier("Alpha_2")
        check("event mood (nervous) not clobbered", mem.get("mood") == "nervous", f"mood={mem.get('mood')}")
        check("Alpha_2 fatigue level 3", mem.get("fatigue", {}).get("level") == 3, str(mem.get("fatigue")))

        # no write when level unchanged
        write_soldier("Alpha_3", mood="calm")
        set_session(50)
        bridge.update_soldier_fatigue([make_member("Alpha_3")])
        mtime1 = (bridge.SOLDIER_MEMORY_DIR / "Alpha_3.json").stat().st_mtime_ns
        set_session(52)  # same level (exhausted)
        bridge.update_soldier_fatigue([make_member("Alpha_3")])
        mtime2 = (bridge.SOLDIER_MEMORY_DIR / "Alpha_3.json").stat().st_mtime_ns
        check("no file write when fatigue level unchanged", mtime1 == mtime2)

        # ── 4. Session-end persistence (B.5 + B.4) ─────────────────────
        set_session(30)
        bridge.app_state["battle_log"] = ["[00:00:01] ORDER: LLM ordered ENGAGE"]
        summary = bridge._write_after_action_report()
        check("report summary non-empty", bool(summary), summary[:60])
        ls_path = bridge.REPORTS_DIR / "last_summary.json"
        check("last_summary.json persisted", ls_path.exists())
        ls = json.loads(ls_path.read_text(encoding="utf-8"))
        check("last_summary.json contains summary", ls.get("summary") == summary)

        mem = read_soldier("Alpha_1")
        deploys = mem.get("previous_deployments") or []
        check("per-soldier previous_deployments recorded", len(deploys) == 1, str(deploys))
        check("deployment entry has date+summary", bool(deploys[0].get("date")) and bool(deploys[0].get("summary")))
        check("fatigue reset to fresh at session end", mem.get("fatigue", {}).get("label") == "fresh", str(mem.get("fatigue")))

        # dedup: second report write does not duplicate
        bridge._write_after_action_report()
        deploys = read_soldier("Alpha_1").get("previous_deployments") or []
        check("deployment entries deduped", len(deploys) == 1, str(len(deploys)))

        # ── 5. Restart survival ────────────────────────────────────────
        restored = bridge._load_last_report_summary()
        check("_load_last_report_summary restores recap", restored == summary, restored[:60])

        # ── 6. Situation text carries the fatigue line ─────────────────
        set_session(5)
        sitrep = make_sitrep(["Alpha_1", "Alpha_2"])
        text = bridge.get_situation_text(sitrep)
        check("fresh session: no fatigue line", "Squad fatigue" not in text)
        set_session(60)
        text = bridge.get_situation_text(sitrep)
        check("fatigued session: fatigue line present", "Squad fatigue" in text and "exhausted" in text)
    finally:
        bridge.SOLDIER_MEMORY_DIR, bridge.SOLDIER_GRAVEYARD_DIR, bridge.REPORTS_DIR = old_dirs
        bridge.app_state["battle_log"] = old_battle_log
        bridge.app_state["session_start_time"] = old_session_start
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} test(s): {FAILURES}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
