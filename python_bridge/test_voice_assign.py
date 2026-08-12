"""Unit tests for C.3 per-soldier voice selection (no audio, no LLM).

Tests run against a TTSHandler with a tmp assignments file:
- assign by index, by voice id string, invalid values rejected
- remove override (None / -1 / "default")
- _resolve_voice_index: override wins, fallback to member_index
- persistence: assignments survive a handler re-creation (bridge restart)
- /tts status exposes voice_options + assignments
- /voice_assign endpoint: valid, invalid, missing name

Usage:  python_bridge\venv\Scripts\python.exe python_bridge\test_voice_assign.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import main as bridge  # noqa: E402  (imports config.json; no server started)
import tts_handler  # noqa: E402

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


def main():
    print("C.3 per-soldier voice selection tests")
    tmp = Path(tempfile.mkdtemp(prefix="c3_voice_"))
    old_file = tts_handler.VOICE_ASSIGNMENTS_FILE
    tts_handler.VOICE_ASSIGNMENTS_FILE = tmp / "voice_assignments.json"
    h = tts_handler.TTSHandler({"enabled": True, "engine": "auto"})
    try:
        n_voices = len(tts_handler.EDGE_VOICES)

        # ── assign + resolve ──────────────────────────────────────────
        check("assign by index", h.assign_voice("Alpha_1", 5) is True)
        check("override stored", h.voice_overrides.get("Alpha_1") == 5)
        check("resolve uses override", h._resolve_voice_index("Alpha_1", 0) == 5)
        check("resolve falls back to index", h._resolve_voice_index("Alpha_2", 2) == 2)
        check("resolve ignores empty name", h._resolve_voice_index("", 3) == 3)

        check("assign by voice id string", h.assign_voice("Alpha_2", "en-US-GuyNeural") is True)
        check("id string resolved to index", h.voice_overrides.get("Alpha_2") == 0)
        check("unknown id rejected", h.assign_voice("Alpha_2", "xx-YY-Bogus") is False)
        check("out-of-range index rejected", h.assign_voice("Alpha_1", n_voices + 5) is False)
        check("non-numeric rejected", h.assign_voice("Alpha_1", "abc") is False)
        check("missing name rejected", h.assign_voice("", 3) is False)

        # ── persistence ───────────────────────────────────────────────
        check("assignments file written", tts_handler.VOICE_ASSIGNMENTS_FILE.exists())
        saved = json.loads(tts_handler.VOICE_ASSIGNMENTS_FILE.read_text(encoding="utf-8"))
        check("file contains overrides", saved == {"Alpha_1": 5, "Alpha_2": 0}, str(saved))

        # reload = bridge restart
        h2 = tts_handler.TTSHandler({"enabled": True, "engine": "auto"})
        check("overrides survive restart", h2.voice_overrides == {"Alpha_1": 5, "Alpha_2": 0}, str(h2.voice_overrides))

        # ── remove ────────────────────────────────────────────────────
        check("remove via None", h.assign_voice("Alpha_1", None) is True)
        check("remove via 'default'", h.assign_voice("Alpha_2", "default") is True)
        check("overrides empty after removal", h.voice_overrides == {}, str(h.voice_overrides))

        # ── status shape ──────────────────────────────────────────────
        h.assign_voice("Alpha_1", 3)
        status = h.get_status()
        check("status has voice_options", status.get("voice_options") == tts_handler.EDGE_VOICES)
        check("status has assignments", status.get("assignments") == {"Alpha_1": tts_handler.EDGE_VOICES[3]}, str(status.get("assignments")))
        check("status voice count", status.get("voices") == n_voices)

        # ── endpoint ──────────────────────────────────────────────────
        from fastapi.testclient import TestClient
        client = TestClient(bridge.app)
        r = client.post("/voice_assign", json={"name": "Bravo_1", "voice": 7})
        check("endpoint assign ok", r.status_code == 200 and r.json().get("status") == "ok", r.text[:80])
        check("endpoint stores override", bridge.tts_handler.voice_overrides.get("Bravo_1") == 7)
        r = client.post("/voice_assign", json={"name": "Bravo_1", "voice": 99})
        check("endpoint rejects bad voice", r.json().get("status") == "error", r.text[:80])
        r = client.post("/voice_assign", json={"voice": 3})
        check("endpoint requires name", r.json().get("status") == "error", r.text[:80])
        r = client.post("/voice_assign", json={"name": "Bravo_1", "voice": "default"})
        check("endpoint removes override", r.json().get("status") == "ok" and "Bravo_1" not in h.voice_overrides)
    finally:
        tts_handler.VOICE_ASSIGNMENTS_FILE = old_file
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} test(s): {FAILURES}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
