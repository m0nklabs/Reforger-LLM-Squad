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


def make_sitrep(names=None, alive=None):
    names = names or [f"Alpha_{i+1}" for i in range(3)]
    alive = alive or {}
    return bridge.SitRepRequest(
        squad=[bridge.SitRepMember(name=n, order="HOLD", sitrep="clear", alive=alive.get(n, True)) for n in names],
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


def test_death_archives_and_grieves():
    print("test_death_archives_and_grieves")
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_1.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_2.json").unlink(missing_ok=True)
    (bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_2.json").unlink(missing_ok=True)
    # Kilo_2 has a history (kills/battles) then the game CONFIRMS the loss
    # via "alive": false (SITREP field). Confirmed deaths are immediate -
    # no grace period needed.
    m2 = bridge.load_soldier_memory("Kilo_2")
    m2["kills"] = 7
    m2["battles_survived"] = 3
    bridge.save_soldier_memory("Kilo_2", m2)
    bridge.app_state["last_squad_names"] = ["Kilo_1", "Kilo_2"]
    bridge.app_state["last_sitrep"] = make_sitrep(["Kilo_1", "Kilo_2"], alive={"Kilo_2": False})
    bridge.app_state["last_sitrep_time"] = time.time()
    bridge.app_state["last_thought_fingerprint"] = None
    bridge.app_state["cached_thoughts"] = None
    bridge.app_state["missing_soldiers"] = {}
    fake = FakeClient(['{"thought": "Kilo 2 is gone...", "mood": "sad"}'])
    bridge.client = fake
    bridge.generate_ai_thoughts("casualty")
    dead = bridge.load_soldier_memory("Kilo_2")
    check("Kilo_2 marked dead", dead.get("status") == "dead" and dead.get("death_date"))
    g = bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_2.json"
    check("graveyard archive exists with final stats", g.exists() and json.load(open(g, encoding="utf-8")).get("kills") == 7)
    surv = bridge.load_soldier_memory("Kilo_1")
    check("survivor mourns relationship", surv.get("relationships", {}).get("Kilo_2", {}).get("label") == "mourned")
    check("survivor has grief opinion", any("fallen:Kilo_2" in o.get("topic", "") for o in surv.get("opinions", [])))
    check("survivor logged kia event", any(e.get("type") == "teammate_kia" for e in surv.get("events", [])))
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_1.json").unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_2.json").unlink(missing_ok=True)
    bridge.SOLDIER_GRAVEYARD_DIR.joinpath("Kilo_2.json").unlink(missing_ok=True)


def test_missing_grace_period_requires_two_cycles():
    print("test_missing_grace_period_requires_two_cycles")
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_3.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_4.json").unlink(missing_ok=True)
    (bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_4.json").unlink(missing_ok=True)
    bridge.load_soldier_memory("Kilo_4")  # create memory file
    bridge.app_state["last_squad_names"] = ["Kilo_3", "Kilo_4"]
    bridge.app_state["missing_soldiers"] = {}
    bridge.app_state["last_sitrep_time"] = time.time()
    bridge.app_state["last_thought_fingerprint"] = None
    bridge.app_state["cached_thoughts"] = None
    # Cycle 1: Kilo_4 missing for the FIRST cycle -> suspicious, but NOT dead
    bridge.app_state["last_sitrep"] = make_sitrep(["Kilo_3"])
    bridge.generate_ai_thoughts("idle")
    m4 = bridge.load_soldier_memory("Kilo_4")
    check("one missing cycle does not kill", m4.get("status") == "alive")
    check("missing counter incremented", bridge.app_state["missing_soldiers"].get("Kilo_4") == 1)
    check("no graveyard entry after one cycle", not (bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_4.json").exists())
    # Cycle 2: still missing -> grace exhausted, marked dead
    bridge.app_state["last_sitrep"] = make_sitrep(["Kilo_3"])
    bridge.generate_ai_thoughts("idle")
    m4 = bridge.load_soldier_memory("Kilo_4")
    check("two missing cycles kill", m4.get("status") == "dead" and m4.get("death_date"))
    check("missing counter cleaned", "Kilo_4" not in bridge.app_state["missing_soldiers"])
    check("graveyard entry after grace", (bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_4.json").exists())
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_3.json").unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_4.json").unlink(missing_ok=True)
    bridge.SOLDIER_GRAVEYARD_DIR.joinpath("Kilo_4.json").unlink(missing_ok=True)


def test_reappearing_member_not_marked_dead():
    print("test_reappearing_member_not_marked_dead")
    # Transient gap (respawn re-link / squad rebuild): member absent for one
    # cycle, back the next -> must survive untouched.
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_5.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_6.json").unlink(missing_ok=True)
    (bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_6.json").unlink(missing_ok=True)
    bridge.load_soldier_memory("Kilo_6")
    bridge.app_state["last_squad_names"] = ["Kilo_5", "Kilo_6"]
    bridge.app_state["missing_soldiers"] = {}
    bridge.app_state["last_sitrep_time"] = time.time()
    bridge.app_state["last_thought_fingerprint"] = None
    bridge.app_state["cached_thoughts"] = None
    # Cycle 1: Kilo_6 missing
    bridge.app_state["last_sitrep"] = make_sitrep(["Kilo_5"])
    bridge.generate_ai_thoughts("idle")
    check("missing counter at 1", bridge.app_state["missing_soldiers"].get("Kilo_6") == 1)
    # Cycle 2: Kilo_6 is BACK (rebuild finished)
    bridge.app_state["last_sitrep"] = make_sitrep(["Kilo_5", "Kilo_6"])
    bridge.generate_ai_thoughts("idle")
    m6 = bridge.load_soldier_memory("Kilo_6")
    check("reappeared member alive", m6.get("status") == "alive" and not m6.get("death_date"))
    check("missing counter reset", "Kilo_6" not in bridge.app_state["missing_soldiers"])
    check("no graveyard entry", not (bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_6.json").exists())
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_5.json").unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_6.json").unlink(missing_ok=True)


def test_already_dead_not_reprocessed():
    print("test_already_dead_not_reprocessed")
    # The game keeps reporting alive=false for a dead member (or the member
    # stays absent): the bridge must not re-archive / re-grieve every cycle.
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_7.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_8.json").unlink(missing_ok=True)
    (bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_8.json").unlink(missing_ok=True)
    bridge.load_soldier_memory("Kilo_8")
    bridge.app_state["last_squad_names"] = ["Kilo_7", "Kilo_8"]
    bridge.app_state["missing_soldiers"] = {}
    bridge.app_state["last_sitrep_time"] = time.time()
    bridge.app_state["last_thought_fingerprint"] = None
    bridge.app_state["cached_thoughts"] = None
    for _ in range(2):  # two consecutive cycles with the same confirmed loss
        bridge.app_state["last_sitrep"] = make_sitrep(["Kilo_7", "Kilo_8"], alive={"Kilo_8": False})
        bridge.generate_ai_thoughts("casualty")
    surv = bridge.load_soldier_memory("Kilo_7")
    grief_opinions = [o for o in surv.get("opinions", []) if "fallen:Kilo_8" in o.get("topic", "")]
    kia_events = [e for e in surv.get("events", []) if e.get("type") == "teammate_kia"]
    check("no duplicate grief opinion", len(grief_opinions) == 1, str(len(grief_opinions)))
    check("no duplicate kia events", len(kia_events) == 1, str(len(kia_events)))
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_7.json").unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_8.json").unlink(missing_ok=True)
    bridge.SOLDIER_GRAVEYARD_DIR.joinpath("Kilo_8.json").unlink(missing_ok=True)


def test_dead_member_does_not_speak():
    print("test_dead_member_does_not_speak")
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_9.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_10.json").unlink(missing_ok=True)
    sitrep = make_sitrep(["Kilo_9", "Kilo_10"], alive={"Kilo_10": False})
    fake = FakeClient(['{"thought": "Kilo 10 was one of us...", "mood": "sad"}'])
    bridge.client = fake
    out = bridge._generate_thoughts_per_soldier(sitrep, "Situation:\nquiet.", "EVENT: casualty\n")
    check("only living member gets a thought", [t["name"] for t in out] == ["Kilo_9"], str([t["name"] for t in out]))
    check("one LLM call for one living member", len(fake.calls) == 1)
    txt = bridge.get_situation_text(sitrep)
    check("KIA marker in situation text", "[KIA - confirmed dead]" in txt)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_9.json").unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_10.json").unlink(missing_ok=True)


def test_rank_promotion_by_deeds():
    print("test_rank_promotion_by_deeds")
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_11.json").unlink(missing_ok=True)
    bridge.ensure_soldier_identity("Kilo_11")
    m = bridge.load_soldier_memory("Kilo_11")
    base_rank = m["identity"]["rank"]
    base_idx = bridge.RANKS.index(base_rank)
    check("test soldier not already top rank", base_idx < len(bridge.RANKS) - 1, base_rank)
    if base_idx >= len(bridge.RANKS) - 1:
        return
    # score = kills*2 + battles*3; give EXACTLY the next rank's threshold
    # (thresholds are even, so kills = threshold/2 with 0 battles)
    target_score = bridge.RANK_SCORE_THRESHOLDS[base_idx + 1]
    m["kills"] = target_score // 2
    m["battles_survived"] = 0
    bridge.save_soldier_memory("Kilo_11", m)
    new_rank = bridge.check_rank_progression("Kilo_11")
    m = bridge.load_soldier_memory("Kilo_11")
    check("promoted one rank", bool(new_rank) and bridge.RANKS.index(new_rank) == base_idx + 1, f"{base_rank}->{new_rank}")
    check("rank persisted in identity", m["identity"]["rank"] == new_rank)
    check("promotion event logged", any(e.get("type") == "promotion" for e in m["events"]))
    check("battle log updated", any("promoted" in e for e in bridge.app_state["battle_log"]))
    check("no double promotion on recheck", bridge.check_rank_progression("Kilo_11") == "")
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_11.json").unlink(missing_ok=True)


def test_multi_rank_promotion():
    print("test_multi_rank_promotion")
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_14.json").unlink(missing_ok=True)
    bridge.ensure_soldier_identity("Kilo_14")
    m = bridge.load_soldier_memory("Kilo_14")
    if bridge.RANKS.index(m["identity"]["rank"]) >= len(bridge.RANKS) - 1:
        bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_14.json").unlink(missing_ok=True)
        return  # base rank already SGT - nothing to jump to
    # score = 8*2 + 3*3 = 25, above every threshold -> jumps to SGT in one check
    m["kills"] = 8
    m["battles_survived"] = 3
    bridge.save_soldier_memory("Kilo_14", m)
    new_rank = bridge.check_rank_progression("Kilo_14")
    check("jumps to SGT from any base", new_rank == "SGT", f"->{new_rank}")
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_14.json").unlink(missing_ok=True)


def test_no_promotion_below_threshold():
    print("test_no_promotion_below_threshold")
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_13.json").unlink(missing_ok=True)
    bridge.ensure_soldier_identity("Kilo_13")
    m = bridge.load_soldier_memory("Kilo_13")
    rank_before = m["identity"]["rank"]
    m["kills"] = 1  # score 2 < 4
    m["battles_survived"] = 0
    bridge.save_soldier_memory("Kilo_13", m)
    check("no promotion below threshold", bridge.check_rank_progression("Kilo_13") == "")
    m = bridge.load_soldier_memory("Kilo_13")
    check("rank unchanged", m["identity"]["rank"] == rank_before)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_13.json").unlink(missing_ok=True)


def test_replacement_resets_rank_and_deeds():
    print("test_replacement_resets_rank_and_deeds")
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_12.json").unlink(missing_ok=True)
    m = bridge.load_soldier_memory("Kilo_12")
    bridge.ensure_soldier_identity("Kilo_12")
    m = bridge.load_soldier_memory("Kilo_12")
    m["identity"]["rank"] = "SGT"
    m["kills"] = 9
    m["battles_survived"] = 4
    m["status"] = "dead"
    m["death_date"] = "2026-08-13T00:00:00"
    bridge.save_soldier_memory("Kilo_12", m)
    bridge.app_state["last_squad_names"] = []
    bridge.app_state["missing_soldiers"] = {}
    bridge.app_state["last_sitrep"] = make_sitrep(["Kilo_12"])
    bridge.app_state["last_sitrep_time"] = time.time()
    bridge.app_state["last_thought_fingerprint"] = None
    bridge.app_state["cached_thoughts"] = None
    fake = FakeClient(['{"thought": "Big boots to fill", "mood": "calm"}'])
    bridge.client = fake
    bridge.generate_ai_thoughts("idle")
    m = bridge.load_soldier_memory("Kilo_12")
    check("replacement rank reset to base", m["identity"]["rank"] == bridge._base_rank("Kilo_12"), m["identity"]["rank"])
    check("replacement deeds reset", m["kills"] == 0 and m["battles_survived"] == 0)
    check("legacy keeps predecessor stats", "9" in (m.get("legacy") or "") and "4" in (m.get("legacy") or ""))
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_12.json").unlink(missing_ok=True)


def test_session_boundary_live_flow_sequence():
    print("test_session_boundary_live_flow_sequence")
    # Reproduces the exact receive_sitrep order: boundary check runs BEFORE
    # sitrep_count is incremented. First SITREP ever: count==0 -> no boundary.
    # Second SITREP after a gap: count==1 -> boundary MUST fire.
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_18.json").unlink(missing_ok=True)
    bridge.load_soldier_memory("Kilo_18")
    bridge.app_state["sitrep_count"] = 0
    bridge.app_state["last_sitrep_time"] = time.time()  # first SITREP just arrived
    bridge.app_state["last_squad_names"] = ["Kilo_18"]
    bridge.app_state["missing_soldiers"] = {}
    bridge.app_state["session_had_members"] = False
    check("no boundary on very first sitrep", bridge._check_session_boundary() is False)
    bridge.app_state["sitrep_count"] = 1  # receive_sitrep increments after the check
    bridge.app_state["last_sitrep_time"] = time.time() - 200  # player left; gap grows
    bridge.app_state["session_had_members"] = True
    check("boundary fires on second sitrep after gap", bridge._check_session_boundary() is True)
    check("report summary stored", bool(bridge.app_state.get("last_report_summary")))
    # cleanup
    for f in bridge.REPORTS_DIR.glob("report_*.json"):
        f.unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_18.json").unlink(missing_ok=True)
    bridge.app_state["last_squad_names"] = []
    bridge.app_state["missing_soldiers"] = {}
    bridge.app_state["last_report_summary"] = None
    bridge.app_state["session_had_members"] = False


def test_after_action_report_written_on_session_end():
    print("test_after_action_report_written_on_session_end")
    import shutil
    for f in bridge.REPORTS_DIR.glob("report_*.json"):
        f.unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_15.json").unlink(missing_ok=True)
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_16.json").unlink(missing_ok=True)
    (bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_16.json").unlink(missing_ok=True)
    # two soldiers with stats; Kilo_16 KIA (file + graveyard copy)
    m = bridge.load_soldier_memory("Kilo_15")
    bridge.ensure_soldier_identity("Kilo_15")
    m = bridge.load_soldier_memory("Kilo_15")
    m["kills"] = 5
    m["battles_survived"] = 2
    bridge.save_soldier_memory("Kilo_15", m)
    m = bridge.load_soldier_memory("Kilo_16")
    bridge.ensure_soldier_identity("Kilo_16")
    m = bridge.load_soldier_memory("Kilo_16")
    m["kills"] = 1
    m["status"] = "dead"
    m["death_date"] = "2026-08-13T00:00:00"
    bridge.save_soldier_memory("Kilo_16", m)
    shutil.copy(bridge.SOLDIER_MEMORY_DIR / "Kilo_16.json", bridge.SOLDIER_GRAVEYARD_DIR / "Kilo_16.json")
    # simulate session end (gap > 90s)
    bridge.app_state["sitrep_count"] = 5
    bridge.app_state["last_sitrep_time"] = time.time() - 200
    bridge.app_state["last_squad_names"] = ["Kilo_15", "Kilo_16"]
    bridge.app_state["missing_soldiers"] = {}
    bridge.app_state["battle_log"] = ["[00:01:00] CONTACT: 3 hostiles detected"]
    bridge.app_state["session_start_time"] = time.time() - 3600
    bridge.app_state["session_had_members"] = True
    check("boundary detected", bridge._check_session_boundary() is True)
    check("squad state reset", bridge.app_state["last_squad_names"] == [])
    summary = bridge.app_state.get("last_report_summary") or ""
    check("summary stored with KIA + stats", "1 KIA" in summary and "Kilo_16" in summary, summary)
    report_files = list(bridge.REPORTS_DIR.glob("report_*.json"))
    check("report file written", len(report_files) == 1, str(len(report_files)))
    with open(report_files[0], encoding="utf-8") as f:
        rep = json.load(f)
    check("report has session duration", rep.get("session_duration_minutes", 0) >= 59, str(rep.get("session_duration_minutes")))
    check("report has battle log", len(rep.get("battle_log", [])) == 1)
    names = [s.get("name") for s in rep.get("soldiers", [])]
    check("report lists soldiers", "Kilo_15" in names and "Kilo_16" in names)
    check("report lists KIA", any(k.get("name") == "Kilo_16" for k in rep.get("kia", [])))
    # second boundary call must NOT write a duplicate report (state already reset)
    report_count = len(list(bridge.REPORTS_DIR.glob("report_*.json")))
    bridge._check_session_boundary()
    check("no duplicate report", len(list(bridge.REPORTS_DIR.glob("report_*.json"))) == report_count)
    # cleanup
    for f in bridge.REPORTS_DIR.glob("report_*.json"):
        f.unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_15.json").unlink(missing_ok=True)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_16.json").unlink(missing_ok=True)
    bridge.SOLDIER_GRAVEYARD_DIR.joinpath("Kilo_16.json").unlink(missing_ok=True)
    bridge.app_state["last_report_summary"] = None
    bridge.app_state["last_squad_names"] = []
    bridge.app_state["missing_soldiers"] = {}
    bridge.app_state["session_had_members"] = False


def test_report_summary_in_prompts():
    print("test_report_summary_in_prompts")
    (bridge.SOLDIER_MEMORY_DIR / "Kilo_17.json").unlink(missing_ok=True)
    bridge.app_state["last_report_summary"] = "3 soldiers deployed, 2 returned, 1 KIA; squad totals: 7 kills, 3 battles"
    fake = FakeClient(['{"thought": "We remember the last deployment.", "mood": "calm"}'])
    bridge.client = fake
    bridge._generate_thoughts_per_soldier(make_sitrep(["Kilo_17"]), "Situation:\nquiet.", "")
    sys_prompt = fake.calls[0][0]["content"]
    check("summary in per-soldier system prompt", "Previous deployment" in sys_prompt and "1 KIA" in sys_prompt)
    fake2 = FakeClient(['{"thought": "Remembering...", "mood": "calm"}'])
    bridge.client = fake2
    bridge._generate_thoughts_batched(make_sitrep(["Kilo_17"]), "Situation:\nquiet.", "")
    batched = fake2.calls[0][1]["content"] if len(fake2.calls) > 0 else ""
    check("summary in batched member lines", "Previous deployment" in batched and "7 kills" in batched)
    bridge.SOLDIER_MEMORY_DIR.joinpath("Kilo_17.json").unlink(missing_ok=True)
    bridge.app_state["last_report_summary"] = None


def test_session_boundary_resets_squad_state():
    print("test_session_boundary_resets_squad_state")
    # SITREP gap > 90s = player disconnected, new session. The old session's
    # squad state must be forgotten so absentees are not false-KIA'd.
    bridge.app_state["sitrep_count"] = 10
    bridge.app_state["last_sitrep_time"] = time.time() - 200
    bridge.app_state["last_squad_names"] = ["Old_1", "Old_2"]
    bridge.app_state["missing_soldiers"] = {"Old_1": 2, "Old_2": 1}
    check("boundary detected", bridge._check_session_boundary() is True)
    check("squad names reset", bridge.app_state["last_squad_names"] == [])
    check("missing counters reset", bridge.app_state["missing_soldiers"] == {})
    # A recent SITREP (same session) must NOT reset
    bridge.app_state["sitrep_count"] = 11
    bridge.app_state["last_sitrep_time"] = time.time() - 5
    bridge.app_state["last_squad_names"] = ["Old_1"]
    bridge.app_state["missing_soldiers"] = {"Old_1": 1}
    check("no boundary within session", bridge._check_session_boundary() is False)
    check("state kept within session", bridge.app_state["last_squad_names"] == ["Old_1"])
    bridge.app_state["last_squad_names"] = []
    bridge.app_state["missing_soldiers"] = {}
    # B.5: the boundary call above also fires the after-action report path -
    # clean up any report it may have written (test isolation)
    for f in bridge.REPORTS_DIR.glob("report_*.json"):
        f.unlink(missing_ok=True)
    bridge.app_state["last_report_summary"] = None


def test_replacement_resurrection_and_legacy():
    print("test_replacement_resurrection_and_legacy")
    (bridge.SOLDIER_MEMORY_DIR / "Lima_1.json").unlink(missing_ok=True)
    m = bridge.load_soldier_memory("Lima_1")
    m["status"] = "dead"
    m["death_date"] = "2026-08-01T12:00:00"
    m["kills"] = 4
    m["battles_survived"] = 2
    bridge.save_soldier_memory("Lima_1", m)
    bridge.app_state["last_squad_names"] = []
    bridge.app_state["last_sitrep"] = make_sitrep(["Lima_1"])
    bridge.app_state["last_sitrep_time"] = time.time()
    bridge.app_state["last_thought_fingerprint"] = None
    bridge.app_state["cached_thoughts"] = None
    fake = FakeClient(['{"thought": "Big boots to fill", "mood": "calm"}'])
    bridge.client = fake
    bridge.generate_ai_thoughts("idle")
    mem = bridge.load_soldier_memory("Lima_1")
    check("replacement resurrected", mem.get("status") == "alive" and mem.get("death_date") is None)
    check("legacy recorded with predecessor stats", "filling their boots" in (mem.get("legacy") or "") and "4" in (mem.get("legacy") or ""))
    check("replacement event logged", any(e.get("type") == "replacement" for e in mem.get("events", [])))
    # legacy must reach the per-soldier system prompt
    fake2 = FakeClient(['{"thought": "Still filling boots", "mood": "calm"}'])
    bridge.client = fake2
    bridge._generate_thoughts_per_soldier(make_sitrep(["Lima_1"]), "Situation:\nquiet.", "")
    check("legacy in system prompt", "Legacy:" in fake2.calls[0][0]["content"] and "filling their boots" in fake2.calls[0][0]["content"])
    bridge.SOLDIER_MEMORY_DIR.joinpath("Lima_1.json").unlink(missing_ok=True)


def test_error_surfacing():
    print("test_error_surfacing")
    bridge.app_state["recent_errors"] = []
    bridge.app_state["errors"] = 0
    try:
        raise RuntimeError("boom test")
    except RuntimeError as e:
        bridge._record_error("test_source", e)
    check("errors counter incremented", bridge.app_state["errors"] == 1)
    errs = bridge.app_state["recent_errors"]
    check("error recorded with source", len(errs) == 1 and errs[0]["source"] == "test_source" and "boom test" in errs[0]["error"])
    check("traceback captured", "RuntimeError" in errs[0]["traceback"] and "test_error_surfacing" in errs[0]["traceback"])
    # rolling window caps at 10
    for i in range(12):
        bridge._record_error("spam", ValueError(f"err {i}"))
    check("rolling window capped at 10", len(bridge.app_state["recent_errors"]) == 10)
    check("oldest dropped", [e["error"] for e in bridge.app_state["recent_errors"]] == [f"ValueError: err {i}" for i in range(2, 12)])
    bridge.app_state["recent_errors"] = []
    bridge.app_state["errors"] = 0


def test_suggestion_approval_flow():
    print("test_suggestion_approval_flow")
    bridge.app_state["pending_suggestions"] = []
    bridge.app_state["suggestion_counter"] = 0
    bridge.app_state["pending_orders"] = []
    # 1. suggest_tactic no longer auto-executes - it submits for approval
    result = bridge.handle_soldier_tool("Alpha_1", {"name": "suggest_tactic", "args": {"formation": "Wedge", "direction": "NE"}})
    check("no auto-executed order", bridge.app_state["pending_orders"] == [])
    sugs = bridge.app_state["pending_suggestions"]
    check("suggestion submitted pending", len(sugs) == 1 and sugs[0]["status"] == "pending" and sugs[0]["formation"] == "Wedge" and sugs[0]["soldier"] == "Alpha_1")
    check("result mentions CO approval", "CO" in result and "approval" in result)
    # 2. CO approves -> the real order is queued
    bridge._approve_suggestion(sugs[0])
    check("accept queues formation order", bridge.app_state["pending_orders"] == [{"cmd": "formation", "formation": "Wedge", "source": "soldier:Alpha_1 (CO approved)"}])
    check("suggestion marked approved", sugs[0]["status"] == "approved")
    # 3. second suggestion stays pending until decided
    bridge.handle_soldier_tool("Alpha_2", {"name": "suggest_tactic", "args": {"formation": "Line"}})
    check("second suggestion pending", bridge.app_state["pending_suggestions"][-1]["status"] == "pending")
    check("no order from undecided suggestion", bridge.app_state["pending_orders"] == [{"cmd": "formation", "formation": "Wedge", "source": "soldier:Alpha_1 (CO approved)"}])
    # 4. trim keeps pending + recent decided, drops old decided
    bridge.app_state["pending_suggestions"][-1]["status"] = "rejected"
    bridge._trim_suggestions()
    check("trim keeps pending + decided", len(bridge.app_state["pending_suggestions"]) == 2)
    bridge.app_state["pending_suggestions"] = []
    bridge.app_state["pending_orders"] = []


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
    print("=== B.1 legacy & mourning unit tests ===")
    test_death_archives_and_grieves()
    test_missing_grace_period_requires_two_cycles()
    test_reappearing_member_not_marked_dead()
    test_already_dead_not_reprocessed()
    test_dead_member_does_not_speak()
    test_session_boundary_resets_squad_state()
    test_replacement_resurrection_and_legacy()
    print("=== B.2 rank progression unit tests ===")
    test_rank_promotion_by_deeds()
    test_multi_rank_promotion()
    test_no_promotion_below_threshold()
    test_replacement_resets_rank_and_deeds()
    print("=== B.5 after-action report unit tests ===")
    test_session_boundary_live_flow_sequence()
    test_after_action_report_written_on_session_end()
    test_report_summary_in_prompts()
    print("=== E.3 error surfacing unit tests ===")
    test_error_surfacing()
    print("=== C.5 suggestion approval flow unit tests ===")
    test_suggestion_approval_flow()
    # cleanup test soldier
    (bridge.SOLDIER_MEMORY_DIR / "Alpha_9.json").unlink(missing_ok=True)
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}: {FAILURES}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run_tests()
