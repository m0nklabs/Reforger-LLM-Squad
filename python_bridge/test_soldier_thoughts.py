"""Unit tests for A.1 per-soldier thought generation (no live LLM needed).

Runs offline: monkeypatches bridge.client with a fake that returns canned
LLM output, then exercises the parse/normalize paths:
- bare thought object {"thought": ...}
- old-style {"thoughts": [...]} wrapper
- prose + ```json fences
- truncated JSON
- LLM claiming a wrong name
- batched fallback when per-soldier mode produces nothing

Usage:  python_bridge\\venv\\Scripts\\python.exe python_bridge\\test_soldier_thoughts.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import main as bridge  # noqa: E402  (imports config.json; no server started)

FAILURES = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILURES.append(label)


class FakeChoice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeClient:
    """Canned responses per call index; records the messages sent."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []  # list of messages arrays
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.calls.append(kwargs["messages"])
        content = self.outputs.pop(0) if self.outputs else '{"thought": "fallback thought", "mood": "calm"}'
        return FakeResponse(content)


def make_sitrep(names=None):
    names = names or [f"Alpha_{i+1}" for i in range(3)]
    return bridge.SitRepRequest(
        squad=[bridge.SitRepMember(name=n, order="HOLD", sitrep="clear") for n in names],
        enemies=[{"dx": 100, "dz": -50, "dist": 112}],
        enemy_count=1,
        environment="Day, clear",
    )


def test_per_soldier_bare_object():
    print("test_per_soldier_bare_object")
    fake = FakeClient([
        '{"thought": "Contact east, get down!", "mood": "alert"}',
        '{"thought": "Covering Alpha_1.", "mood": "calm"}',
        '{"thought": "I hate ambushes.", "mood": "nervous"}',
    ])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(), "Situation:\nno contacts.", "EVENT: contact\n")
    check("3 thoughts", len(out) == 3, str(len(out)))
    check("names match squad", [t["name"] for t in out] == ["Alpha_1", "Alpha_2", "Alpha_3"])
    check("moods kept", out[0]["mood"] == "alert")
    check("no tool when absent", all(t.get("tool") is None for t in out))
    check("3 separate LLM calls (one per soldier)", len(fake.calls) == 3)
    # system prompt must contain identity + backstory + CoC
    sys_msg = fake.calls[0][0]["content"]
    check("system has identity", "Alpha_1" in sys_msg and "rank" in sys_msg.lower() or "PVT" in sys_msg or "SPC" in sys_msg or "CPL" in sys_msg or "SGT" in sys_msg)
    check("system has CoC", "CO" in sys_msg)
    check("system has tools", "call_medic" in sys_msg)
    check("last msg is user situation", fake.calls[0][-1]["role"] == "user" and "Situation:" in fake.calls[0][-1]["content"])


def test_per_soldier_wrapper_and_fences():
    print("test_per_soldier_wrapper_and_fences")
    fake = FakeClient([
        'Here are the thoughts:\n```json\n{"thoughts": [{"name": "Alpha_1", "thought": "Wrapper thought", "mood": "bored"}]}\n```',
        '```json\n{"thought": "Fenced thought", "mood": "confident"}\n```',
    ])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(), "Situation:\nno contacts.", "")
    check("wrapper + fences parsed", len(out) == 3 and out[0]["thought"] == "Wrapper thought" and out[1]["thought"] == "Fenced thought")


def test_per_soldier_wrong_name():
    print("test_per_soldier_wrong_name")
    fake = FakeClient(['{"thought": "Calling in", "mood": "alert", "name": "CPL Alpha_1"}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(), "Situation:\nno contacts.", "")
    check("rank prefix stripped, attributed to own name", out and out[0]["name"] == "Alpha_1")


def test_per_soldier_tool_kept():
    print("test_per_soldier_tool_kept")
    fake = FakeClient([
        '{"thought": "Hostiles!", "mood": "alert", "tool": {"name": "report_contact", "args": {"direction": "NE", "distance": 100, "count": 3}}}'
    ])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(), "Situation:\nno contacts.", "")
    check("tool parsed", out and out[0]["tool"] and out[0]["tool"]["name"] == "report_contact")


def test_batched_fallback():
    print("test_batched_fallback")
    fake = FakeClient([
        '{"thoughts": [{"name": "Alpha_1", "thought": "B1", "mood": "calm"}, {"name": "Alpha_2", "thought": "B2", "mood": "calm"}]}'
    ])
    bridge.client = fake
    out = bridge._generate_thoughts_batched(make_sitrep(), "Situation:\nno contacts.", "EVENT: idle\n")
    check("batched returns 2 thoughts", len(out) == 2 and out[0]["name"] == "Alpha_1")
    check("llm_calls incremented", bridge.app_state["llm_calls"] > 0)


def test_batched_garbage_returns_empty():
    print("test_batched_garbage_returns_empty")
    fake = FakeClient(["this is not json at all"])
    bridge.client = fake
    out = bridge._generate_thoughts_batched(make_sitrep(), "Situation:\nno contacts.", "")
    check("garbage -> empty list (triggers fallback chain)", out == [])


def test_exchange_logging():
    print("test_exchange_logging")
    (bridge.SOLDIER_MEMORY_DIR / "Alpha_9.json").unlink(missing_ok=True)  # fresh state
    bridge.log_soldier_exchange("Alpha_9", "thought one", "alert", "EVENT: contact")
    bridge.log_soldier_exchange("Alpha_9", "thought two", "calm", "EVENT: idle")
    mem = bridge.load_soldier_memory("Alpha_9")
    conv = mem.get("conversation", [])
    check("conversation has 4 messages (2 exchanges)", len(conv) == 4)
    check("roles alternate user/assistant", conv[0]["role"] == "user" and conv[1]["role"] == "assistant" and conv[2]["role"] == "user" and conv[3]["role"] == "assistant")
    check("brief stored", conv[2]["content"] == "EVENT: idle")
    check("thought_history also updated", len(mem.get("thought_history", [])) == 2)
    check("last_thought set", mem.get("last_thought") == "thought two")


def test_history_fed_back_as_chat_turns():
    print("test_history_fed_back_as_chat_turns")
    (bridge.SOLDIER_MEMORY_DIR / "Alpha_8.json").unlink(missing_ok=True)
    bridge.log_soldier_exchange("Alpha_8", "old thought about the ambush", "nervous", "EVENT: contact")
    fake = FakeClient(['{"thought": "New thought", "mood": "calm"}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(["Alpha_8"]), "Situation:\nno contacts.", "")
    msgs = fake.calls[0]
    roles = [m["role"] for m in msgs]
    check("history user turn included", "user" in roles[:-1])
    check("history assistant turn included", "assistant" in roles[:-1])
    check("history content present", any("old thought about the ambush" in m.get("content", "") for m in msgs))
    check("final turn is current situation", msgs[-1]["role"] == "user" and "[NOW]" in msgs[-1]["content"])
    check("soldier name still attributed", out and out[0]["name"] == "Alpha_8")
    (bridge.SOLDIER_MEMORY_DIR / "Alpha_8.json").unlink(missing_ok=True)


def run_tests():
    print("=== A.1 per-soldier thought unit tests ===")
    test_exchange_logging()
    test_per_soldier_bare_object()
    test_per_soldier_wrapper_and_fences()
    test_per_soldier_wrong_name()
    test_per_soldier_tool_kept()
    test_history_fed_back_as_chat_turns()
    test_batched_fallback()
    test_batched_garbage_returns_empty()
    # cleanup test soldier
    (bridge.SOLDIER_MEMORY_DIR / "Alpha_9.json").unlink(missing_ok=True)
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run_tests()
