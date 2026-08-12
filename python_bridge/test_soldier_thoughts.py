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
import time
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


def test_per_soldier_string_in_wrapper():
    print("test_per_soldier_string_in_wrapper")
    fake = FakeClient(['{"thoughts": ["Alpha_1: plain text thought here"]}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(["Alpha_1"]), "Situation:\nno contacts.", "")
    check("string entry salvaged as thought", out and out[0]["name"] == "Alpha_1" and out[0]["thought"] == "Alpha_1: plain text thought here")


def test_batched_string_entries_dropped():
    print("test_batched_string_entries_dropped")
    fake = FakeClient(['{"thoughts": ["not an object", {"name": "Alpha_1", "thought": "Real thought", "mood": "calm"}]}'])
    bridge.client = fake
    out = bridge._generate_thoughts_batched(make_sitrep(["Alpha_1"]), "Situation:\nno contacts.", "")
    check("string entries dropped, dicts kept", len(out) == 1 and out[0]["thought"] == "Real thought")


def test_per_soldier_bare_json_string():
    print("test_per_soldier_bare_json_string")
    # LLM sometimes returns a bare quoted string instead of an object:
    #   "Alpha_1: moving to the treeline"
    # extract_json_block must return None (not the str), and the per-soldier
    # path must skip gracefully instead of crashing on data.get().
    fake = FakeClient(['"Alpha_1: moving to the treeline"'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(["Alpha_1"]), "Situation:\nno contacts.", "")
    check("bare string -> no crash, no thought", out == [])


def test_per_soldier_bare_json_array():
    print("test_per_soldier_bare_json_array")
    # Bare JSON array instead of an object: ["Alpha_1: ..."]
    fake = FakeClient(['["Alpha_1: array text"]'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(["Alpha_1"]), "Situation:\nno contacts.", "")
    check("bare array -> no crash, no thought", out == [])


def test_extract_json_block_string_returns_none():
    print("test_extract_json_block_string_returns_none")
    check("bare string -> None", bridge.extract_json_block('"just a string"') is None)
    check("bare array -> None", bridge.extract_json_block('["a", "b"]') is None)
    check("dict still parsed", isinstance(bridge.extract_json_block('{"thought": "ok"}'), dict))


def test_chatter_helper_empty_first_cycle():
    print("test_chatter_helper_empty_first_cycle")
    fresh = make_sitrep(["Bravo_1", "Bravo_2"])
    check("no chatter before anyone spoke", bridge.get_squadmate_recent_thoughts(fresh, "Bravo_1") == "")


def test_chatter_helper_excludes_self():
    print("test_chatter_helper_excludes_self")
    (bridge.SOLDIER_MEMORY_DIR / "Charlie_1.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Charlie_2.json").unlink(missing_ok=True)
    bridge.log_soldier_exchange("Charlie_1", "I am Charlie 1 speaking", "calm", "EVENT: idle")
    bridge.log_soldier_exchange("Charlie_2", "Charlie 2 here, moving up", "alert", "EVENT: idle")
    sitrep = make_sitrep(["Charlie_1", "Charlie_2"])
    chatter = bridge.get_squadmate_recent_thoughts(sitrep, "Charlie_1")
    check("chatter has squadmate's words", "Charlie 2 here, moving up" in chatter)
    check("chatter excludes own words", "I am Charlie 1 speaking" not in chatter)
    check("chatter includes name + mood", "Charlie_2" in chatter and "alert" in chatter)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Charlie_1.json").unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Charlie_2.json").unlink(missing_ok=True)


def test_chatter_fed_into_prompt():
    print("test_chatter_fed_into_prompt")
    (bridge.SOLDIER_MEMORY_DIR / "Delta_1.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Delta_2.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Delta_3.json").unlink(missing_ok=True)
    bridge.log_soldier_exchange("Delta_2", "I hate ambushes, stay sharp", "nervous", "EVENT: contact")
    bridge.log_soldier_exchange("Delta_3", "Covering you, Delta 1", "confident", "EVENT: contact")
    fake = FakeClient(['{"thought": "Delta 2 is spooked, I got their back", "mood": "calm"}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(["Delta_1", "Delta_2", "Delta_3"]), "Situation:\nno contacts.", "EVENT: idle\n")
    check("thought generated for first soldier", len(out) >= 1 and out[0]["name"] == "Delta_1")
    msgs = fake.calls[0]
    last_user = msgs[-1]["content"]
    check("prompt has squadmate chatter block", "Squadmate chatter" in last_user)
    check("prompt contains Delta_2's words", "I hate ambushes" in last_user)
    check("prompt contains Delta_3's words", "Covering you" in last_user)
    check("system prompt mentions reacting to squadmates", "Squadmate chatter" in msgs[0]["content"])
    for n in ("Delta_1", "Delta_2", "Delta_3"):
        bridge.SOLDIER_MEMORY_DIR.joinpath(f"{n}.json").unlink(missing_ok=True)


def test_chatter_in_brief_log():
    print("test_chatter_in_brief_log")
    (bridge.SOLDIER_MEMORY_DIR / "Echo_1.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Echo_2.json").unlink(missing_ok=True)
    bridge.log_soldier_exchange("Echo_2", "Heard something in the treeline", "alert", "EVENT: contact")
    fake = FakeClient(['{"thought": "Acknowledged", "mood": "calm"}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(["Echo_1", "Echo_2"]), "Situation:\nquiet.", "EVENT: idle\n")
    # simulate what generate_ai_thoughts does: log exchange with chatter in brief
    sitrep = make_sitrep(["Echo_1", "Echo_2"])
    chatter = bridge.get_squadmate_recent_thoughts(sitrep, "Echo_1")
    brief = "EVENT: idle"
    if chatter:
        heard = " ; ".join(l.strip("- ").strip() for l in chatter.splitlines())[:180]
        brief += f" | heard: {heard}"
    bridge.log_soldier_exchange("Echo_1", "Acknowledged", "calm", brief)
    mem = bridge.load_soldier_memory("Echo_1")
    conv = mem.get("conversation", [])
    check("brief includes heard chatter", any("heard: " in m.get("content", "") and "treeline" in m.get("content", "") for m in conv if m.get("role") == "user"))
    for n in ("Echo_1", "Echo_2"):
        bridge.SOLDIER_MEMORY_DIR.joinpath(f"{n}.json").unlink(missing_ok=True)


def test_tool_result_stored_and_fed_back():
    print("test_tool_result_stored_and_fed_back")
    (bridge.SOLDIER_MEMORY_DIR / "Foxtrot_1.json").unlink(missing_ok=True)
    bridge.app_state["last_sitrep"] = make_sitrep(["Foxtrot_1"])
    bridge.app_state["last_sitrep_time"] = time.time()
    bridge.app_state["last_thought_fingerprint"] = None
    bridge.app_state["cached_thoughts"] = None
    # Cycle 1: soldier calls report_contact -> generate_ai_thoughts must store the result
    fake = FakeClient(['{"thought": "Contact NE!", "mood": "alert", "tool": {"name": "report_contact", "args": {"direction": "NE", "distance": 100, "count": 2}}}'])
    bridge.client = fake
    r1 = bridge.generate_ai_thoughts("contact")
    check("cycle1 thought carries tool", r1["thoughts"] and r1["thoughts"][0].get("tool"))
    mem = bridge.load_soldier_memory("Foxtrot_1")
    check("result stored in memory", "2 hostiles" in (mem.get("last_tool_result") or ""))
    # Cycle 2: fresh generation -> consequence must appear in the next prompt
    bridge.app_state["last_thought_fingerprint"] = None
    fake2 = FakeClient(['{"thought": "Good, contact went out", "mood": "calm"}'])
    bridge.client = fake2
    bridge.generate_ai_thoughts("idle")
    msgs = fake2.calls[0]
    last_user = msgs[-1]["content"]
    check("prompt contains last action result", "Your last action's result" in last_user and "2 hostiles" in last_user)
    check("system prompt mentions consequences", "result" in msgs[0]["content"].lower())
    bridge.SOLDIER_MEMORY_DIR.joinpath("Foxtrot_1.json").unlink(missing_ok=True)


def test_no_result_no_consequence_block():
    print("test_no_result_no_consequence_block")
    (bridge.SOLDIER_MEMORY_DIR / "Golf_1.json").unlink(missing_ok=True)
    fake = FakeClient(['{"thought": "Nothing to report", "mood": "calm"}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(["Golf_1"]), "Situation:\nquiet.", "EVENT: idle\n")
    msgs = fake.calls[0]
    check("no consequence block when no tool was called", "last action's result" not in msgs[-1]["content"])
    bridge.SOLDIER_MEMORY_DIR.joinpath("Golf_1.json").unlink(missing_ok=True)


def test_tool_result_in_batched_lines():
    print("test_tool_result_in_batched_lines")
    (bridge.SOLDIER_MEMORY_DIR / "Hotel_1.json").unlink(missing_ok=True)
    result = bridge.handle_soldier_tool("Hotel_1", {"name": "report_clear", "args": {}})
    mem = bridge.load_soldier_memory("Hotel_1")
    mem["last_tool_result"] = result  # same store step generate_ai_thoughts does
    bridge.save_soldier_memory("Hotel_1", mem)
    fake = FakeClient(['{"thoughts": [{"name": "Hotel_1", "thought": "Clear is logged", "mood": "calm"}]}'])
    bridge.client = fake
    out = bridge._generate_thoughts_batched(make_sitrep(["Hotel_1"]), "Situation:\nquiet.", "")
    check("batched prompt includes last action result", fake.calls[0][-1]["content"].count("Last action result") == 1)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Hotel_1.json").unlink(missing_ok=True)


def test_identity_fed_into_system_prompt():
    print("test_identity_fed_into_system_prompt")
    (bridge.SOLDIER_MEMORY_DIR / "India_1.json").unlink(missing_ok=True)
    sitrep = bridge.SitRepRequest(squad=[bridge.SitRepMember(name="India_1", order="HOLD", sitrep="clear", identity="Miller 'Ghost' Johnson")])
    fake = FakeClient(['{"thought": "Ghost here, holding", "mood": "calm"}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(sitrep, "Situation:\nquiet.", "")
    msgs = fake.calls[0]
    check("in-game identity in system prompt", "Miller 'Ghost' Johnson" in msgs[0]["content"])
    bridge.SOLDIER_MEMORY_DIR.joinpath("India_1.json").unlink(missing_ok=True)


def test_no_identity_no_block():
    print("test_no_identity_no_block")
    (bridge.SOLDIER_MEMORY_DIR / "Juliet_1.json").unlink(missing_ok=True)
    fake = FakeClient(['{"thought": "Holding", "mood": "calm"}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(make_sitrep(["Juliet_1"]), "Situation:\nquiet.", "")
    msgs = fake.calls[0]
    check("no identity block when game sends none", "military records" not in msgs[0]["content"])
    bridge.SOLDIER_MEMORY_DIR.joinpath("Juliet_1.json").unlink(missing_ok=True)


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
    test_per_soldier_string_in_wrapper()
    test_batched_string_entries_dropped()
    test_per_soldier_bare_json_string()
    test_per_soldier_bare_json_array()
    test_extract_json_block_string_returns_none()
    print("=== A.2 soldier-to-soldier chatter unit tests ===")
    test_chatter_helper_empty_first_cycle()
    test_chatter_helper_excludes_self()
    test_chatter_fed_into_prompt()
    test_chatter_in_brief_log()
    print("=== A.3 tool consequence awareness unit tests ===")
    test_tool_result_stored_and_fed_back()
    test_no_result_no_consequence_block()
    test_tool_result_in_batched_lines()
    print("=== A.4 identity integration unit tests ===")
    test_identity_fed_into_system_prompt()
    test_no_identity_no_block()
    # cleanup test soldier
    (bridge.SOLDIER_MEMORY_DIR / "Alpha_9.json").unlink(missing_ok=True)
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run_tests()
