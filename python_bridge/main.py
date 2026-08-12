"""
Reforger LLM Squad Control - Python Bridge
FastAPI server that bridges Arma Reforger with OpenAI-compatible LLM proxy.

F1.3: Route sync complete. Game sends via GET ?data=<urlencoded_json>.
F2.3: Waypoint execution — LLM orders → AIWaypoint → squad moves.
F2.x: Live orders — /orders endpoint for real-time debugging without game restart.
"""

import json
import time
import os
import math
import logging
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, ConfigDict, field_validator
from openai import OpenAI

from pathlib import Path
from datetime import datetime

# =======================================================================
# Fix: Handle Reforger's HTTP Upgrade headers gracefully (root cause fix)
# =======================================================================
# Reforger's REST client (Enforce RestContext) sends "Connection: Upgrade" 
# headers on normal HTTP requests. Uvicorn's h11/httptools HTTP protocol layer 
# treats ANY Upgrade header as a potential WebSocket connection and logs 
# "WARNING: Unsupported upgrade request." when it can't handle it.
#
# This is NOT a suppression — it's the CORRECT HTTP behavior:
# - WebSocket upgrades (Upgrade: websocket) still work if ws protocol is configured
# - Non-WebSocket upgrades are treated as normal HTTP (the request is processed normally)
# - The only difference from default uvicorn: no warning for a normal HTTP/1.1 request
#   that happens to include an Upgrade header (which is valid per RFC 7230 §6.1)
#
# This patch is module-level so it works whether the bridge is started via
# `python main.py` or `python -m uvicorn main:app` (CLI mode from start_bridge.bat)
import uvicorn.protocols.http.h11_impl
import uvicorn.protocols.http.httptools_impl

_original_should_upgrade_h11 = uvicorn.protocols.http.h11_impl.H11Protocol._should_upgrade
_original_should_upgrade_httptools = uvicorn.protocols.http.httptools_impl.HttpToolsProtocol._should_upgrade

def _should_upgrade_graceful(self):
    """Handle Upgrade headers gracefully: only upgrade for actual WebSocket requests."""
    upgrade = self._get_upgrade()
    if upgrade == b"websocket" and self._should_upgrade_to_ws():
        return True
    # Non-WebSocket upgrades (e.g. h2c, or Reforger's custom) → treat as normal HTTP
    return False

uvicorn.protocols.http.h11_impl.H11Protocol._should_upgrade = _should_upgrade_graceful
uvicorn.protocols.http.httptools_impl.HttpToolsProtocol._should_upgrade = _should_upgrade_graceful

# Also patch zttp if available (newer uvicorn HTTP implementation)
try:
    import uvicorn.protocols.http.zttp_impl
    uvicorn.protocols.http.zttp_impl.ZttpProtocol._should_upgrade = _should_upgrade_graceful
except ImportError:
    pass  # zttp not installed (optional dependency)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

logging.basicConfig(
    level=getattr(logging, CONFIG["logging"]["level"]),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), CONFIG["logging"]["file"])),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("reforger_bridge")

client = OpenAI(
    base_url=CONFIG["llm"]["base_url"],
    api_key=CONFIG["llm"]["api_key"],
    timeout=float(CONFIG["llm"]["timeout_seconds"])
)

# Phase 2: Voice pipeline (Whisper STT + PTT key)
from voice_handler import VoiceHandler
voice_handler = VoiceHandler(
    CONFIG.get("voice", {}),
    on_transcription=None  # set in lifespan after call_llm is available
)

# Phase 3: TTS squad feedback (edge-tts + pyttsx3 fallback)
from tts_handler import TTSHandler
tts_handler = TTSHandler(CONFIG.get("tts", {}))

app = FastAPI(title="Reforger LLM Squad Control Bridge")

# --- Pydantic Models ---

class SitRepMember(BaseModel):
    name: str = ""
    order: str = "HOLD"
    sitrep: str = "clear"

class SitRepRequest(BaseModel):
    source: str = "game"
    type: str = "SITREP"
    squad: List[SitRepMember] = []
    enemies: List[dict] = []  # F3.4: enemy positions (dx, dz, dist relative to squad)
    enemy_count: int = 0
    environment: str = ""  # F3.5: terrain + time description
    model_config = ConfigDict(extra="allow")

class CommandRequest(BaseModel):
    source: str = "game"
    type: str = "COMMAND"
    command: str = ""
    model: str = "llama3"
    model_config = ConfigDict(extra="allow")

class SitRepResponse(BaseModel):
    status: str = "ok"
    action: str = "HOLD"
    target_offset: Optional[List[float]] = None
    voice_reply: str = ""
    timestamp: float = Field(default_factory=time.time)

    @field_validator('target_offset', mode='before')
    @classmethod
    def parse_target_offset(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except:
                return None
        if isinstance(v, list):
            return v
        return None

ISSUE_ORDER_FUNCTION = {
    "name": "issue_order",
    "description": "Issue a tactical order to a squad. target_offset is RELATIVE to the squad's current position in meters: [dx, dz] where positive dx=east, positive dz=south.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["ENGAGE", "MOVE", "SUPPRESS", "FLANK", "RETREAT", "HOLD", "MOUNT", "DISMOUNT", "MEDIC"]},
            "target_offset": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Relative offset [dx, dz] in meters from squad position. For ENGAGE, point toward the enemy."
            },
            "voice_reply": {"type": "string"}
        },
        "required": ["action", "voice_reply"]
    }
}

SYSTEM_PROMPT = """You are a tactical AI adjutant in Arma Reforger.
You control a squad of 4 AI soldiers. Issue tactical orders based on the situation.

{situation}

Respond with valid JSON only. Direction guide for target_offset [dx, dz]:
- East  = positive dx, e.g. [100, 0]
- West  = negative dx, e.g. [-100, 0]
- North = negative dz, e.g. [0, -100]
- South = positive dz, e.g. [0, 100]
Keep offsets 50-300m. No enemies nearby = HOLD with [0, 0].
If enemies are detected, ENGAGE with offset toward nearest enemy, or FLANK to approach from the side, or RETREAT if outnumbered.
MOUNT = order squad to enter nearest vehicle (for fast travel or retreat). DISMOUNT = exit vehicle.
Use MOUNT when squad needs to cover large distances quickly or retreat from overwhelming force.
MEDIC = emergency rescue: move squad to downed leader position to revive and protect. Use when leader_state=DOWNED.
If LEADER STATUS shows DOWNED, prioritize MEDIC action — get to the leader and provide cover.
Remember events from RECENT BATTLE EVENTS when making decisions — this is your squad's memory."""


# ─── F7: Individual AI Soldier Memory ──────────────────────────────────
SOLDIER_MEMORY_DIR = Path("ai_soldiers")
SOLDIER_GRAVEYARD_DIR = Path("ai_soldiers/graveyard")
SOLDIER_RETENTION_DAYS = 7  # Keep dead soldier files for 7 days

def ensure_soldier_dirs():
    """Create soldier memory directories if they don't exist."""
    SOLDIER_MEMORY_DIR.mkdir(exist_ok=True)
    SOLDIER_GRAVEYARD_DIR.mkdir(exist_ok=True)

def load_soldier_memory(name: str) -> dict:
    """Load a soldier's personal memory file. Create if not exists."""
    ensure_soldier_dirs()
    filepath = SOLDIER_MEMORY_DIR / f"{name}.json"
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass  # Corrupt file, recreate
    
    # Create new soldier memory
    return {
        "name": name,
        "personality": None,  # Assigned on first thought generation
        "birth_date": datetime.now().isoformat(),
        "death_date": None,
        "status": "alive",
        "events": [],  # Personal event log: [{"time": ..., "type": ..., "desc": ...}]
        "opinions": [],  # Formed opinions: [{"topic": ..., "opinion": ...}]
        "mood": "neutral",
        "last_thought": None,
        "relationships": {},  # {"Alpha_2": "trusted", "Alpha_3": "annoying"}
        "kills": 0,
        "battles_survived": 0,
        # F8.1: Identity + backstory (generated on first access by ensure_soldier_identity)
        "identity": None,
        "backstory": None,
        "thought_history": [],  # F8.1: own thoughts, rolling window of 10
    }

def save_soldier_memory(name: str, memory: dict):
    """Save a soldier's personal memory file."""
    ensure_soldier_dirs()
    filepath = SOLDIER_MEMORY_DIR / f"{name}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)

def log_soldier_event(name: str, event_type: str, description: str):
    """Log an event to a soldier's personal memory."""
    mem = load_soldier_memory(name)
    mem["events"].append({
        "time": datetime.now().isoformat(),
        "type": event_type,
        "desc": description,
    })
    # Keep last 50 events per soldier (rolling window)
    if len(mem["events"]) > 50:
        mem["events"] = mem["events"][-50:]
    save_soldier_memory(name, mem)

def mark_soldier_dead(name: str):
    """Mark a soldier as dead. Retain file for debugging."""
    mem = load_soldier_memory(name)
    mem["status"] = "dead"
    mem["death_date"] = datetime.now().isoformat()
    save_soldier_memory(name, mem)

def cleanup_dead_soldiers():
    """Archive dead soldier files older than retention period."""
    ensure_soldier_dirs()
    cutoff = time.time() - (SOLDIER_RETENTION_DAYS * 86400)
    for filepath in SOLDIER_MEMORY_DIR.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mem = json.load(f)
            if mem.get("status") == "dead" and mem.get("death_date"):
                death_time = datetime.fromisoformat(mem["death_date"]).timestamp()
                if death_time < cutoff:
                    # Archive to graveyard
                    archive_path = SOLDIER_GRAVEYARD_DIR / filepath.name
                    filepath.rename(archive_path)
        except (json.JSONDecodeError, IOError, ValueError):
            pass  # Skip corrupt files

def get_soldier_history_summary(name: str, max_events: int = 5) -> str:
    """Get a formatted summary of a soldier's personal history for LLM prompt."""
    mem = load_soldier_memory(name)
    lines = []
    
    # Status
    if mem["status"] == "dead":
        lines.append(f"[KIA - died {mem.get('death_date', 'unknown')[:10]}]")
    
    # Personality
    p = mem.get("personality", "unknown")
    lines.append(f"Personality: {p}")
    
    # Recent events
    events = mem.get("events", [])
    if events:
        recent = events[-max_events:]
        lines.append("Recent experiences:")
        for e in recent:
            t = e.get("time", "")[-8:-3]  # HH:MM
            lines.append(f"  [{t}] {e.get('type', '?')}: {e.get('desc', '')}")
    else:
        lines.append("No prior combat experience (new recruit).")
    
    # Battle count
    battles = mem.get("battles_survived", 0)
    if battles > 0:
        lines.append(f"Survived {battles} engagement(s).")
    
    # Kills
    kills = mem.get("kills", 0)
    if kills > 0:
        lines.append(f"Confirmed kills: {kills}")
    
    # Last mood
    mood = mem.get("mood", "neutral")
    if mood != "neutral":
        lines.append(f"Current mood: {mood}")
    
    return "\n".join(lines)


# ─── F8.1: Soldier Identity + Backstory ─────────────────────────────────
# Deterministic identity generation (hash-based, like personalities):
# rank, role, age, origin, deployments, backstory. Generated once per soldier
# on first access, stored in their memory file. Same name → same identity.

RANKS = ["PVT", "PFC", "SPC", "CPL", "SGT"]
ROLES = [
    "Rifleman", "Automatic Rifleman", "Grenadier",
    "Medic", "Team Leader", "Designated Marksman"
]
ORIGINS = [
    "Texas", "Ohio", "Georgia", "California", "Pennsylvania",
    "Arizona", "New York", "Montana", "Kentucky", "Florida"
]

# Backstory templates keyed by personality trait (filled with role/deployments)
BACKSTORY_TEMPLATES = {
    "AGGRESSIVE": "grew up hunting in {origin} and joined to fight, not to stand guard. {deploy} deployments taught them that the best defense is a fast, loud offense.",
    "CAUTIOUS": "a careful {origin} native who survived {deploy} deployment(s) by trusting cover and patience over heroics. Every corner hides something.",
    "JOKER": "from {origin}, keeps morale up with dark jokes. {deploy} deployment(s) in and still laughing — because crying is bad for aiming.",
    "VETERAN": "old hand from {origin} with {deploy} deployment(s) behind them. Seen everything, fears nothing except paperwork.",
    "ROOKIE": "fresh out of training from {origin}. This is their first deployment and they're trying hard not to look scared.",
    "STEADY": "quiet professional from {origin}. {deploy} deployment(s) of doing the job right, no drama, no mistakes.",
}


def _name_hash(name: str, salt: str) -> int:
    import hashlib
    return int(hashlib.md5((name + salt).encode()).hexdigest(), 16)


def ensure_soldier_identity(name: str) -> dict:
    """Generate (once) and return a soldier's identity + backstory.
    Deterministic per name: same name always gets the same identity.
    Migrates existing memory files by adding the identity block."""
    mem = load_soldier_memory(name)
    if mem.get("identity") and mem.get("backstory"):
        return mem

    personality = mem.get("personality") or app_state["ai_personalities"].get(name, "STEADY")

    rank = RANKS[_name_hash(name, "rank") % len(RANKS)]
    role = ROLES[_name_hash(name, "role") % len(ROLES)]
    origin = ORIGINS[_name_hash(name, "origin") % len(ORIGINS)]
    age = 21 + (_name_hash(name, "age") % 18)          # 21..38
    deployments = 1 + (_name_hash(name, "deploy") % 3)  # 1..3
    months = 2 + (_name_hash(name, "months") % 22)      # 2..23 in theater

    template = BACKSTORY_TEMPLATES.get(personality, BACKSTORY_TEMPLATES["STEADY"])
    backstory = template.format(origin=origin, deploy=deployments)
    backstory = backstory[:1].upper() + backstory[1:]  # sentence case

    mem["identity"] = {
        "rank": rank,
        "role": role,
        "age": age,
        "origin": origin,
        "time_in_theater_months": months,
        "deployments": deployments,
    }
    mem["backstory"] = backstory
    mem["thought_history"] = mem.get("thought_history", [])  # F8.1 conversation history
    save_soldier_memory(name, mem)
    return mem


def get_soldier_identity_summary(name: str) -> str:
    """One-line identity summary for LLM prompts."""
    mem = ensure_soldier_identity(name)
    i = mem.get("identity", {})
    return (
        f"{i.get('rank', 'PVT')} {name} — {i.get('role', 'Rifleman')}, "
        f"{i.get('age', 25)} yrs, from {i.get('origin', '?')}, "
        f"{i.get('deployments', 1)} deployment(s), {i.get('time_in_theater_months', 6)} months in theater"
    )


def get_soldier_backstory(name: str) -> str:
    """The soldier's generated personal backstory."""
    mem = ensure_soldier_identity(name)
    return mem.get("backstory", "No backstory recorded.")


def log_soldier_thought(name: str, thought: str, mood: str):
    """F8.1: Append a soldier's own thought to their conversation history."""
    mem = load_soldier_memory(name)
    mem["last_thought"] = thought
    mem["mood"] = mood or mem.get("mood", "neutral")
    hist = mem.get("thought_history", [])
    hist.append({"time": datetime.now().isoformat(), "thought": thought})
    mem["thought_history"] = hist[-10:]  # rolling window of 10
    save_soldier_memory(name, mem)


# ─── F8.3: Soldier Tools — agent actions that trigger game logic ───────
# A soldier's thought JSON may include an optional "tool" block:
#   {"name": "call_medic", "args": {"target": "Alpha_3"}}
# Tools translate into real game orders (queued via /orders which the game
# polls every 2s) or battle-log events. This makes soldiers AGENTS, not
# commentators: their decisions change what happens in the world.

TOOL_ORDER_MAP = {
    "call_medic": "medic",          # emergency rescue order
    "suggest_tactic": "formation",  # formation change
}


def handle_soldier_tool(name: str, tool: dict) -> str:
    """Process one soldier tool call. Returns a human-readable result string."""
    tool_name = (tool.get("name") or "").strip()
    args = tool.get("args") or {}
    if not tool_name:
        return ""

    result = f"{name} used {tool_name}"

    if tool_name == "report_contact":
        direction = args.get("direction", "?")
        distance = args.get("distance", "?")
        count = args.get("count", 1)
        add_battle_event("CONTACT", f"{name} reports {count} hostile(s) {distance}m {direction}")
        result += f" -> {count} hostiles {distance}m {direction} logged"
        logger.info(f"[TOOL] {result}")

    elif tool_name == "report_clear":
        add_battle_event("CONTACT", f"{name} reports area clear")
        result += " -> area clear logged"
        logger.info(f"[TOOL] {result}")

    elif tool_name == "request_orders":
        add_battle_event("ORDER", f"{name} requests new orders")
        result += " -> request logged"
        logger.info(f"[TOOL] {result}")

    elif tool_name == "report_status":
        health = args.get("health", "?")
        ammo = args.get("ammo", "?")
        log_soldier_event(name, "status", f"Reported status: health={health}, ammo={ammo}")
        result += f" -> health={health}, ammo={ammo} recorded"
        logger.info(f"[TOOL] {result}")

    elif tool_name == "call_medic":
        target = args.get("target", name)
        add_battle_event("CRITICAL", f"{name} calls MEDIC for {target}!")
        # Queue the medic order for the game (squad moves to downed soldier)
        app_state["pending_orders"].append({"cmd": "medic", "source": f"soldier:{name}"})
        result += f" -> MEDIC order queued for {target}"
        logger.info(f"[TOOL] {result}")

    elif tool_name == "suggest_tactic":
        formation = args.get("formation", "Line")
        direction = args.get("direction", "")
        add_battle_event("ORDER", f"{name} suggests {formation} formation" + (f" heading {direction}" if direction else ""))
        app_state["pending_orders"].append({"cmd": "formation", "formation": formation, "source": f"soldier:{name}"})
        result += f" -> {formation} formation order queued"
        logger.info(f"[TOOL] {result}")

    else:
        logger.info(f"[TOOL] {name} tried unknown tool: {tool_name}")
        result += f" (unknown tool {tool_name}, ignored)"

    return result


def get_soldier_thought_history(name: str, max_items: int = 3) -> str:
    """F8.1: The soldier's own recent thoughts (conversation memory)."""
    mem = ensure_soldier_identity(name)
    hist = mem.get("thought_history", [])[-max_items:]
    if not hist:
        return "No prior thoughts on record."
    return "\n".join(f"- earlier: {h.get('thought', '')}" for h in hist)


# ─── F8.4: Social dynamics — bonds & opinions between squadmates ───────
# Relationships evolve from shared experiences (events). Each event nudges
# a sentiment score toward squadmates; strong scores become opinions that
# are fed into the thought-generation prompt.

RELATIONSHIP_EVENTS = {
    "clear": ("bond", +1, "fought alongside"),
    "contact": ("respect", +1, "held together under fire"),
    "casualty": ("respect", +2, "fought to the end"),
    "teammate_kia": ("respect", +2, "gave everything"),
    "leader_downed": ("worry", +1, "leader is down"),
    "leader_recovered": ("trust", +1, "leader came back"),
    "order_change": ("adapt", +1, "handled new orders"),
}

# Personality friction: how one personality views another. Positive = bonus,
# negative = friction. Drives variance so not everyone ends up "reliable".
PERSONALITY_FRICTION = {
    ("VETERAN", "ROOKIE"): -2, ("ROOKIE", "VETERAN"): +1,   # veteran finds rookie green
    ("CAUTIOUS", "AGGRESSIVE"): -2, ("AGGRESSIVE", "CAUTIOUS"): -1,
    ("CAUTIOUS", "JOKER"): -2, ("JOKER", "CAUTIOUS"): -1,
    ("STEADY", "JOKER"): -1, ("JOKER", "STEADY"): +1,
    ("AGGRESSIVE", "ROOKIE"): -1, ("VETERAN", "VETERAN"): +1,
}

RELATIONSHIP_OPINIONS = [
    (8, "brother-in-arms", "{subject} is a brother-in-arms, would follow anywhere"),
    (6, "trusted", "{subject} is trusted, solid under pressure"),
    (4, "reliable", "{subject} is reliable, does the job"),
    (1, "okay", "{subject} is okay, does what's needed"),
    (-4, "reckless", "{subject} is reckless, takes too many risks"),
    (-6, "unpredictable", "{subject} is unpredictable, hard to trust"),
]


def update_social_bonds(event: str, squad_names: list):
    """Update each soldier's relationships/opinions based on a shared event.
    Deterministic sentiment model: each event type nudges a score toward
    every squadmate; strong scores materialize as opinions."""
    if event not in RELATIONSHIP_EVENTS:
        return
    kind, delta, reason = RELATIONSHIP_EVENTS[event]
    for name in squad_names:
        mem = load_soldier_memory(name)
        rels = mem.get("relationships", {})
        opinions = mem.get("opinions", [])
        own_personality = mem.get("personality") or app_state["ai_personalities"].get(name, "STEADY")
        for other in squad_names:
            if other == name:
                continue
            other_mem = load_soldier_memory(other)
            other_personality = other_mem.get("personality") or app_state["ai_personalities"].get(other, "STEADY")
            # Personality friction modifies how this event lands
            friction = PERSONALITY_FRICTION.get((own_personality, other_personality), 0)
            entry = rels.get(other, {"score": 0, "label": "unknown"})
            entry["score"] = entry.get("score", 0) + delta + friction
            # Recompute label from score
            label = "unknown"
            for threshold, lbl, _ in RELATIONSHIP_OPINIONS:
                if entry["score"] >= threshold:
                    label = lbl
                    break
            entry["label"] = label
            rels[other] = entry
        mem["relationships"] = rels
        # Materialize strong opinions (cap at 6 stored opinions, refresh text)
        opinion_topics = {o.get("topic") for o in opinions}
        for other in squad_names:
            if other == name:
                continue
            entry = rels.get(other, {})
            score = entry.get("score", 0)
            best = None
            for threshold, lbl, template in RELATIONSHIP_OPINIONS:
                if score >= threshold:
                    best = (lbl, template)
                    break  # first (strongest) matching label wins
            if best and abs(score) >= 4 and other not in opinion_topics:
                lbl, template = best
                opinions.append({
                    "topic": other,
                    "opinion": template.format(subject=other),
                    "strength": lbl,
                    "score": score,
                })
                opinion_topics.add(other)
        mem["opinions"] = opinions[-6:]
        save_soldier_memory(name, mem)


def get_social_summary(name: str) -> str:
    """Format a soldier's relationships + opinions for LLM prompts."""
    mem = load_soldier_memory(name)
    rels = mem.get("relationships", {})
    opinions = mem.get("opinions", [])
    lines = []
    if rels:
        rel_parts = []
        for other, entry in rels.items():
            if entry.get("label") and entry["label"] != "unknown":
                rel_parts.append(f"{other}: {entry['label']}")
        if rel_parts:
            lines.append("Squad relationships: " + ", ".join(rel_parts))
    for o in opinions[-3:]:
        lines.append(f"Opinion: {o.get('opinion', '')}")
    return "\n".join(lines)


app_state = {
    "last_sitrep": None,
    "health_check_time": time.time(),
    "llm_calls": 0,
    "errors": 0,
    "last_status": None,
    "last_waypoint": None,
    "sitrep_count": 0,
    "command_count": 0,
    "pending_orders": [],  # F2.x: live orders queue
    "last_sitrep_fingerprint": None,  # dedup: skip LLM if situation unchanged
    "last_llm_response": None,       # cached response for unchanged situations
    "sitrep_skipped": 0,             # count of skipped LLM calls
    # F2.7: Individual AI brains
    "ai_personalities": {},           # name -> personality (assigned on first SITREP)
    "cached_thoughts": None,         # cached thoughts for unchanged situation
    "last_thought_fingerprint": None,
    "thought_calls": 0,
    # F3.1: Stavka OPFOR AI
    "stavka_cycles": 0,
    "last_stavka_fingerprint": None,
    "cached_stavka_orders": None,
    # Player activity tracking
    "last_sitrep_time": time.time(),  # updated on every SITREP; LLM skipped if stale > 90s
    # F5: Battle Memory — rolling event log for LLM context
    "battle_log": [],                # last 15 events, included in LLM prompts
    "last_leader_state": "alive",
    "last_enemy_count": -1,   # F8.5: previous SITREP enemy count (kill attribution)
    "kill_rotation": 0,       # F8.5: round-robin kill attribution index
    "last_squad_names": [],  # Track squad member names for death detection
    "soldier_memory_enabled": True,    # F6: track leader state changes
}

def add_battle_event(event_type: str, description: str):
    """F5: Add an event to the battle memory log."""
    event = f"[{time.strftime('%H:%M:%S')}] {event_type}: {description}"
    app_state["battle_log"].append(event)
    while len(app_state["battle_log"]) > 15:
        app_state["battle_log"].pop(0)
    logger.info(f"Battle log: {event}")


def get_battle_memory(max_events=8):
    """F5: Return formatted battle memory for LLM prompt."""
    if not app_state.get("battle_log"):
        return ""
    recent = app_state["battle_log"][-max_events:]
    return "\nRECENT BATTLE EVENTS (most recent last):\n" + "\n".join(f"  {e}" for e in recent)


def get_situation_text(sitrep: SitRepRequest) -> str:
    lines = []
    pos = None
    if sitrep.model_extra:
        pos = sitrep.model_extra.get("position")
    if pos:
        if isinstance(pos, list):
            lines.append(f"Squad position: ({pos[0]:.1f}, {pos[1] if len(pos) > 1 else 0:.1f}, {pos[2] if len(pos) > 2 else 0:.1f})")
        else:
            lines.append(f"Squad position: {pos}")
    # F6: Leader state (downed/alive/dead)
    leader_state = "alive"
    if sitrep.model_extra:
        leader_state = sitrep.model_extra.get("leader_state", "alive")
    if leader_state != "alive":
        lines.append(f"LEADER STATUS: {leader_state.upper()}!")
    for m in sitrep.squad:
        lines.append(f"  {m.name}: order={m.order}, sitrep={m.sitrep}")
    # F3.4: Enemy contact info
    if sitrep.enemy_count > 0 and sitrep.enemies:
        lines.append(f"ENEMY CONTACT: {sitrep.enemy_count} hostiles detected:")
        for e in sitrep.enemies[:5]:  # max 5 enemies in prompt to save tokens
            dx = e.get("dx", 0)
            dz = e.get("dz", 0)
            dist = e.get("dist", 0)
            # Convert to compass direction
            compass = "unknown"
            if dist > 0:
                angle = math.degrees(math.atan2(-dz, dx))
                if angle < 0: angle += 360
                dirs = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]
                idx = int((angle + 22.5) / 45) % 8
                compass = dirs[idx]
            lines.append(f"  Enemy {dist:.0f}m {compass} (offset dx={dx:.0f}, dz={dz:.0f})")
    else:
        lines.append("No enemy contacts reported.")

    # F3.5: Environment description
    if sitrep.environment:
        lines.append(f"Environment: {sitrep.environment}")

    return "Squad status:\n" + "\n".join(lines) if lines else "No squad data."

# ─── Robust JSON extraction ──────────────────────────────────────────
# The Ollama proxy sometimes prepends prose or wraps JSON in ```json fences.
# json.loads() on raw content fails then. Extract the first {...} block instead.

def extract_json_block(content: str):
    """Extract a JSON object from LLM output that may contain prose/fences.
    Returns parsed dict, or None if no valid JSON object found.
    Handles: prose prefix, ```json fences, truncated output (best-effort
    repair by parsing individual member objects)."""
    if not content:
        return None
    # Strip markdown code fences
    text = content.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1].strip()
        else:
            text = text.lstrip("`").strip()
    # Find first { ... last } and try parsing that span
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        # Best-effort repair for truncated output: parse individual {..} objects
        repaired = _repair_truncated_json(candidate)
        if repaired is not None:
            return repaired
    # Last resort: try the raw text as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _repair_truncated_json(text: str):
    """Try to salvage a truncated/irregular JSON blob.
    Strategy: split on `},{` boundaries, parse each object individually,
    and collect them under "thoughts" if they look like member objects."""
    objects = []
    depth = 0
    cur = []
    for ch in text:
        if ch == "{":
            depth += 1
            cur.append(ch)
        elif ch == "}":
            depth -= 1
            cur.append(ch)
            if depth == 0:
                chunk = "".join(cur)
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict):
                        objects.append(obj)
                except json.JSONDecodeError:
                    pass
                cur = []
        elif cur:
            cur.append(ch)
    if not objects:
        return None
    # If any object has "thoughts" as a list, return it
    for obj in objects:
        if isinstance(obj.get("thoughts"), list):
            return obj
    # Otherwise treat collected objects as member thoughts
    return {"thoughts": objects}


def _sitrep_fingerprint(sitrep: SitRepRequest) -> str:
    """Compute a fingerprint of the tactical situation. If this matches the last one, skip LLM call."""
    parts = [f"members={len(sitrep.squad)}"]
    for m in sitrep.squad:
        parts.append(f"{m.name}:{m.order}:{m.sitrep}")
    # Round position to 50m grid — tiny movements don't change the tactical picture
    if sitrep.model_extra:
        pos = sitrep.model_extra.get("position")
        if pos and isinstance(pos, list) and len(pos) >= 2:
            parts.append(f"pos={int(pos[0]//50)*50},{int(pos[2] if len(pos)>2 else pos[1])//50*50}")
    # F3.4: Include enemy count + rough positions in fingerprint
    parts.append(f"enemies={sitrep.enemy_count}")
    for e in sitrep.enemies[:5]:
        parts.append(f"e{int(e.get('dx',0)//50)}:{int(e.get('dz',0)//50)}")
    # F3.5: Include environment (time changes trigger new calls)
    parts.append(f"env={sitrep.environment[:20] if sitrep.environment else 'none'}")
    # F6: Leader state in fingerprint (state change triggers new LLM call)
    if sitrep.model_extra:
        parts.append(f"leader={sitrep.model_extra.get('leader_state', 'alive')}")
    return "|".join(parts)

def call_llm(command: str, situation: str) -> SitRepResponse:
    app_state["llm_calls"] += 1
    # F5: Include battle memory in situation
    situation = situation + get_battle_memory()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(situation=situation)},
        {"role": "user", "content": command}
    ]

    # Try function calling first
    try:
        response = client.chat.completions.create(
            model=CONFIG["llm"]["model"],
            messages=messages,
            tools=[{"type": "function", "function": ISSUE_ORDER_FUNCTION}],
            tool_choice={"type": "function", "function": {"name": "issue_order"}},
            max_tokens=CONFIG["llm"]["max_tokens"],
            temperature=0.3
        )
        if response.choices and response.choices[0].message.tool_calls:
            tool_call = response.choices[0].message.tool_calls[0]
            args = json.loads(tool_call.function.arguments)
            target_offset = args.get("target_offset", None)
            if isinstance(target_offset, str):
                try:
                    target_offset = json.loads(target_offset)
                except:
                    target_offset = None
            return SitRepResponse(status="ok", action=args.get("action", "HOLD"), target_offset=target_offset, voice_reply=args.get("voice_reply", ""))
        else:
            logger.warning("LLM returned no tool_calls, falling back to JSON mode")
    except Exception as e1:
        logger.warning(f"Function calling failed: {e1}")

    # Fallback: JSON mode
    try:
        response = client.chat.completions.create(
            model=CONFIG["llm"]["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(situation=situation)},
                {"role": "user", "content": command + '\nReturn JSON: {"action": "HOLD|MOVE|ATTACK|RETREAT", "target_offset": [dx, dz], "voice_reply": "..."}'}
            ],
            response_format={"type": "json_object"},
            max_tokens=CONFIG["llm"]["max_tokens"],
            temperature=0.3
        )
        content = response.choices[0].message.content if response.choices else ""
        if not content or not content.strip():
            logger.error("LLM returned empty content")
            return SitRepResponse(status="ok", action="HOLD", target_offset=None, voice_reply="")
        data = json.loads(content)
        to = data.get("target_offset", None)
        if isinstance(to, str):
            try: to = json.loads(to)
            except: to = None
        return SitRepResponse(status="ok", action=data.get("action", "HOLD"), target_offset=to, voice_reply=data.get("voice_reply", ""))
    except Exception as e2:
        logger.error(f"LLM call failed: {e2}")
        app_state["errors"] += 1
        return SitRepResponse(status="error", action="HOLD", voice_reply="Command timeout, holding position.")

        return SitRepResponse(status="error", action="HOLD", voice_reply="Command timeout, holding position.")

# =======================================================================
# F2.7: Individual AI Brains — personality + thought generation
# =======================================================================
PERSONALITIES = ["AGGRESSIVE", "CAUTIOUS", "JOKER", "VETERAN", "ROOKIE", "STEADY"]

AI_THOUGHT_SYSTEM_PROMPT = """You generate internal thoughts for AI squad members in Arma Reforger.
Each member has a personality. Generate ONE short thought per member (max 15 words).

Personalities:
- AGGRESSIVE: wants to attack, push forward, impatient
- CAUTIOUS: worried about ambushes, wants cover, overwatch
- JOKER: cracks jokes, lightens the mood, doesn't take things seriously
- VETERAN: calm, experienced, tactical observations
- ROOKIE: nervous, eager to prove themselves, asks questions
- STEADY: professional, focused, mission-oriented

When the situation is quiet/clear, members may chat with squadmates naturally.
When in combat, thoughts should be tactical and urgent.

TOOLS — each member MAY optionally request ONE tool action if the situation warrants it:
- report_contact(direction, distance, count): enemy sighting, report to squad
- report_clear(): area is clear
- request_orders(): ask CO for new orders
- report_status(health, ammo): report own condition
- call_medic(target): request medical help for a downed squadmate
- suggest_tactic(formation, direction): suggest a tactical change (formation: Column/Line/Wedge/Diamond, direction: N/E/S/W/NE/NW/SE/SW)
Only call a tool when it genuinely helps. Most of the time no tool is needed.

Return JSON: {"thoughts": [{"name": "Alpha_1", "thought": "...", "mood": "...", "tool": {"name": "call_medic", "args": {"target": "Alpha_3"}}}]}
"tool" is optional — omit it when no action is needed.
Moods: alert, bored, nervous, confident, annoyed, scared, calm, excited."""

def assign_personalities(squad):
    """Assign stable personalities to squad members (deterministic by name)."""
    import hashlib
    for m in squad:
        if m.name not in app_state["ai_personalities"]:
            h = int(hashlib.md5(m.name.encode()).hexdigest(), 16)
            personality = PERSONALITIES[h % len(PERSONALITIES)]
            app_state["ai_personalities"][m.name] = personality

def generate_ai_thoughts(event: str = ""):
    """Generate thoughts for squad members, triggered by events.
    
    Each soldier has their own personal memory file. Thoughts are generated
    based on their personal history, not just the current SITREP.
    
    Event types:
    - "contact": enemy detected, thoughts should be tactical/urgent
    - "clear": enemies eliminated, thoughts about survival/relief
    - "order_change": LLM order changed, react to new orders
    - "casualty": squad member lost, grief/anger/determination
    - "idle": no events for 60s, casual banter
    - "leader_downed": leader is down, panic/medic urgency
    - "leader_recovered": leader back up, relief
    """
    sitrep = app_state.get("last_sitrep")
    if not sitrep or not sitrep.squad:
        return {"thoughts": []}

    # Safety net: skip LLM if no SITREPs received in 90s
    if time.time() - app_state.get("last_sitrep_time", 0) > 90:
        return {"thoughts": []}

    assign_personalities(sitrep.squad)

    # ─── Per-soldier memory: log events to individual files ────────────
    current_names = set()
    for m in sitrep.squad:
        current_names.add(m.name)
        # Ensure soldier memory file exists
        mem = load_soldier_memory(m.name)
        # Assign personality if not set
        if not mem.get("personality"):
            p = app_state["ai_personalities"].get(m.name, "STEADY")
            mem["personality"] = p
            save_soldier_memory(m.name, mem)
        
        # Log events to individual soldier memory
        if event == "contact":
            log_soldier_event(m.name, "contact", "Enemy contact detected")
        elif event == "clear":
            log_soldier_event(m.name, "clear", "Area cleared, enemies eliminated")
            mem = load_soldier_memory(m.name)
            mem["battles_survived"] = mem.get("battles_survived", 0) + 1
            save_soldier_memory(m.name, mem)
        elif event == "order_change":
            log_soldier_event(m.name, "order_change", f"Orders changed to {m.order}")
        elif event == "casualty":
            log_soldier_event(m.name, "casualty", "Squad member lost in action")
        elif event == "leader_downed":
            log_soldier_event(m.name, "leader_down", "Squad leader was downed!")

    # ─── Death detection: check for missing squad members ──────────────
    last_names = set(app_state.get("last_squad_names", []))
    if last_names:
        dead_soldiers = last_names - current_names
        for dead_name in dead_soldiers:
            mark_soldier_dead(dead_name)
            # Log to surviving soldiers
            for m in sitrep.squad:
                log_soldier_event(m.name, "teammate_kia", f"{dead_name} was killed in action")
    
    app_state["last_squad_names"] = list(current_names)
    
    # F8.4: Update social bonds/opinions from this shared event
    update_social_bonds(event, list(current_names))
    
    # Cleanup old dead soldier files
    cleanup_dead_soldiers()

    # Dedup: still use fingerprint but event changes it
    fp = _sitrep_fingerprint(sitrep) + "|event=" + event
    if fp == app_state["last_thought_fingerprint"] and app_state["cached_thoughts"] and event == "":
        return app_state["cached_thoughts"]

    app_state["last_thought_fingerprint"] = fp
    app_state["thought_calls"] += 1

    # ─── Build per-soldier context with personal memory ────────────────
    situation = get_situation_text(sitrep) + get_battle_memory(3)
    
    # Event-specific context
    event_context = ""
    if event == "contact":
        event_context = "\nEVENT: Enemy contact detected! The squad just spotted hostiles. Thoughts should reflect urgency and combat awareness.\n"
    elif event == "clear":
        event_context = "\nEVENT: All enemies eliminated. Area is clear. Thoughts should reflect relief, survival, maybe dark humor.\n"
    elif event == "order_change":
        event_context = "\nEVENT: Orders just changed. React to the new order immediately.\n"
    elif event == "casualty":
        event_context = "\nEVENT: A squad member just went down. React with grief, anger, or determination. Keep it short.\n"
    elif event == "idle":
        event_context = "\nCONTEXT: Quiet moment, no immediate threats. Casual banter, checking on each other, or observing surroundings.\n"
    elif event == "leader_downed":
        event_context = "\nEVENT: The squad leader is DOWN! Panic, urgency, calls for medic, protective instinct.\n"
    elif event == "leader_recovered":
        event_context = "\nEVENT: The squad leader is back up. Relief, determination, ready to continue.\n"
    
    # Build member descriptions WITH identity + personal memory + conversation history
    member_lines = []
    for m in sitrep.squad:
        p = app_state["ai_personalities"].get(m.name, "STEADY")
        identity = get_soldier_identity_summary(m.name)
        backstory = get_soldier_backstory(m.name)
        history = get_soldier_history_summary(m.name, max_events=5)
        own_thoughts = get_soldier_thought_history(m.name)
        social = get_social_summary(m.name)  # F8.4: relationships + opinions
        member_lines.append(
            f"- {identity}\n  Personality: {p}\n  Backstory: {backstory}\n{history}\n"
            f"{social}\n"
            f"  Own recent thoughts:\n{own_thoughts}\n"
            f"  Current: order={m.order}, sitrep={m.sitrep}"
        )
    
    members_text = "\n".join(member_lines)
    prompt = (
        f"Situation:\n{situation}\n{event_context}\n"
        f"Squad members (with identity, backstory and personal history):\n{members_text}\n\n"
        "Generate one thought per member reacting to the situation. The thought should reflect "
        "their rank, role, backstory AND their personal experiences. A veteran who has survived "
        "5 battles sounds different from a rookie on their first day. A medic thinks about wounds, "
        "a grenadier about angles. Stay in character.\n\n"
        "TOOLS: each member may include an optional \"tool\" field in their JSON object when "
        "the situation genuinely calls for action. Use report_contact for enemy sightings, "
        "call_medic when a squadmate is down, suggest_tactic to propose a formation change, "
        "report_status when hurt or low on ammo. Most members most of the time omit the tool "
        "field — only act when it matters. Example: "
        "{\"name\": \"Alpha_2\", \"thought\": \"...\", \"mood\": \"alert\", "
        "\"tool\": {\"name\": \"report_contact\", \"args\": {\"direction\": \"NE\", "
        "\"distance\": 150, \"count\": 3}}}"
    )

    try:
        response = client.chat.completions.create(
            model=CONFIG["llm"]["model"],
            messages=[
                {"role": "system", "content": AI_THOUGHT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=600,
            temperature=0.7
        )
        content = response.choices[0].message.content if response.choices else ""
        data = extract_json_block(content)
        if data:
            thoughts = data.get("thoughts", data) if isinstance(data, dict) else data
            if not isinstance(thoughts, list):
                thoughts = []
            result = {"thoughts": thoughts}
            app_state["cached_thoughts"] = result
            app_state["llm_calls"] += 1
            # F8.1: Store each soldier's thought in their personal conversation history
            # F8.3: Process optional tool calls (report_contact, call_medic, suggest_tactic...)
            for t in thoughts:
                tname = t.get("name", "?")
                tthought = t.get("thought", "")
                tmood = t.get("mood", "neutral")
                log_soldier_thought(tname, tthought, tmood)
                tool = t.get("tool")
                if isinstance(tool, dict) and tool.get("name"):
                    handle_soldier_tool(tname, tool)
            logger.info(f"AI thoughts generated: {len(thoughts)} thoughts for {len(sitrep.squad)} members")
            for t in thoughts:
                name = t.get("name", "?")
                thought = t.get("thought", "")[:80]
                mood = t.get("mood", "?")
                logger.info(f"  [{name} ({mood})] {thought}")
            return result
    except Exception as e:
        logger.error(f"AI thought generation failed: {e}")
        app_state["errors"] += 1

    return {"thoughts": []}
@app.get("/health")
async def health_check():
    uptime = time.time() - app_state["health_check_time"]
    return {
        "status": "healthy", "uptime_seconds": round(uptime, 2),
        "llm_calls": app_state["llm_calls"], "errors": app_state["errors"],
        "sitreps_received": app_state["sitrep_count"], "commands_received": app_state["command_count"],
        "pending_orders": len(app_state["pending_orders"]),
        "sitreps_skipped_llm": app_state.get("sitrep_skipped", 0),
        "players_active": (time.time() - app_state.get("last_sitrep_time", 0)) < 90,
        "secs_since_last_sitrep": round(time.time() - app_state.get("last_sitrep_time", 0), 1),
        "proxy": CONFIG["llm"]["base_url"], "model": CONFIG["llm"]["model"],
        "tts_enabled": tts_handler.enabled
    }

# =======================================================================
# GET /dashboard - Web UI command dashboard
# =======================================================================
from fastapi.responses import HTMLResponse

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    """Serve the command dashboard web UI."""
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>dashboard.html not found</h1>", status_code=404)

# =======================================================================
# GET /tts - Phase 3: TTS handler status
# =======================================================================
@app.get("/tts")
async def tts_status():
    return tts_handler.get_status()

# =======================================================================
# /orders — LIVE command queue (F2.x: debug without game restart)
# POST /orders  {cmd: "spawn"} or {cmd: "move", offset: [100, 0]} or {cmd: "hold"}
# GET /orders   — returns first pending order, or {cmd: null}
# =======================================================================
@app.get("/orders")
async def get_orders():
    if app_state["pending_orders"]:
        order = app_state["pending_orders"].pop(0)
        logger.info(f"Order delivered to game: {order}")
        return order
    return {"cmd": None}

@app.post("/orders")
async def post_orders(request: Request):
    data = await _get_data(request)
    if data:
        app_state["pending_orders"].append(data)
        logger.info(f"Order queued: {data}")
        return {"status": "ok", "queued": len(app_state["pending_orders"])}
    return {"status": "error", "msg": "no data"}

# =======================================================================
# /sitrep — GET (query param) or POST (body)
# =======================================================================
@app.get("/sitrep")
@app.post("/sitrep")
async def receive_sitrep(request: Request):
    app_state["sitrep_count"] += 1
    app_state["last_sitrep_time"] = time.time()
    data = await _get_data(request)
    if data:
        try:
            sitrep = SitRepRequest(**data)
        except Exception as e:
            logger.warning(f"SITREP parse error: {e}")
            sitrep = SitRepRequest()
    else:
        sitrep = SitRepRequest(squad=[SitRepMember(name=f"Alpha_{i+1}") for i in range(4)])
    app_state["last_sitrep"] = sitrep

    # Dedup: skip LLM call if tactical situation hasn't changed
    fp = _sitrep_fingerprint(sitrep)
    if fp == app_state["last_sitrep_fingerprint"] and app_state["last_llm_response"]:
        app_state["sitrep_skipped"] += 1
        logger.info(f"SITREP #{app_state['sitrep_count']}: {len(sitrep.squad)} members — unchanged, skipping LLM (skipped: {app_state['sitrep_skipped']})")
        return app_state["last_llm_response"]

    # Situation changed — call LLM
    app_state["last_sitrep_fingerprint"] = fp
    logger.info(f"SITREP #{app_state['sitrep_count']}: {len(sitrep.squad)} members — situation changed, calling LLM")
    situation = get_situation_text(sitrep)
    response = call_llm(command=f"SITREP review: {len(sitrep.squad)} squad members deployed.", situation=situation)
    app_state["last_llm_response"] = response
    # Phase 3: TTS speak
    if response.voice_reply:
        tts_handler.speak(response.voice_reply, member_index=0)
    # F5: Log battle events
    if response.action != "HOLD":
        add_battle_event("ORDER", f"LLM ordered {response.action}")
    if sitrep.enemy_count > 0:
        add_battle_event("CONTACT", f"{sitrep.enemy_count} hostiles detected")
    # F6: Track leader state changes
    leader_state = "alive"
    if sitrep.model_extra:
        leader_state = sitrep.model_extra.get("leader_state", "alive")
    if leader_state == "downed" and app_state.get("last_leader_state") != "downed":
        add_battle_event("CRITICAL", "Squad leader is DOWN! Medic rescue needed!")
    elif leader_state == "alive" and app_state.get("last_leader_state") == "downed":
        add_battle_event("RECOVERY", "Squad leader is back on feet!")
    app_state["last_leader_state"] = leader_state

    # F8.5: Kill attribution — if enemy count dropped since last SITREP,
    # the squad took hostiles down. Assign the kill to a squad member
    # (rotating, so the kill tally spreads across the squad over time).
    prev_enemies = app_state.get("last_enemy_count", sitrep.enemy_count)
    if prev_enemies > sitrep.enemy_count:
        kills_this_cycle = prev_enemies - sitrep.enemy_count
        members = [m.name for m in sitrep.squad]
        if members:
            for _ in range(kills_this_cycle):
                idx = app_state.get("kill_rotation", 0) % len(members)
                app_state["kill_rotation"] = idx + 1
                killer = members[idx]
                mem = load_soldier_memory(killer)
                mem["kills"] = mem.get("kills", 0) + 1
                save_soldier_memory(killer, mem)
                log_soldier_event(killer, "kill", "Confirmed hostile eliminated")
            add_battle_event("CONTACT", f"Squad eliminated {kills_this_cycle} hostile(s)")
            logger.info(f"F8.5: {kills_this_cycle} kill(s) attributed (rotation at {app_state.get('kill_rotation', 0)})")
    app_state["last_enemy_count"] = sitrep.enemy_count

    logger.info(f"LLM order: action={response.action}, offset={response.target_offset}, leader={leader_state}")
    return response

# =======================================================================
# /command — GET (query param) or POST (body)
# =======================================================================
@app.get("/command")
@app.post("/command")
async def receive_command(request: Request):
    app_state["command_count"] += 1
    data = await _get_data(request)
    if data:
        try: cmd = CommandRequest(**data)
        except: cmd = CommandRequest(command="UNKNOWN")
    else:
        cmd = CommandRequest(command="UNKNOWN")
    logger.info(f"Command #{app_state['command_count']}: '{cmd.command}'")
    situation = get_situation_text(app_state["last_sitrep"]) if app_state["last_sitrep"] else "No SITREP data."
    response = call_llm(command=cmd.command, situation=situation)
    # Phase 3: TTS speak
    if response.voice_reply:
        tts_handler.speak(response.voice_reply, member_index=0)
    logger.info(f"LLM order: action={response.action}")
    return response

# =======================================================================
# /status
# =======================================================================
@app.get("/status")
async def receive_status_get(request: Request):
    if request.query_params.get("data"):
        return await _process_status(request)
    last_sitrep = app_state["last_sitrep"].model_dump() if app_state["last_sitrep"] else None
    return {"state": {k: v for k, v in app_state.items() if k != "last_sitrep"}, "last_sitrep": last_sitrep}

@app.post("/status")
async def receive_status_post(request: Request):
    return await _process_status(request)

async def _process_status(request: Request):
    data = await _get_data(request)
    if data:
        logger.info(f"Status from game: llm_ready={data.get('llm_ready')}, squad_count={data.get('squad_count')}")
        app_state["last_status"] = data
    return {"status": "ok", "timestamp": time.time()}

# =======================================================================
# /waypoint
# =======================================================================
@app.get("/waypoint")
@app.post("/waypoint")
async def receive_waypoint(request: Request):
    data = await _get_data(request)
    if data:
        logger.info(f"Waypoint: {data.get('id', '?')} at {data.get('position', '?')}")
        app_state["last_waypoint"] = data
    return {"status": "ok", "timestamp": time.time()}

    return {"status": "ok", "timestamp": time.time()}

# =======================================================================
# /ai_thought — F2.7: Individual AI Brains
# =======================================================================
@app.get("/ai_thought")
async def get_ai_thought(event: str = ""):
    result = generate_ai_thoughts(event)
    return result

# =======================================================================
# F3.1: Stavka OPFOR strategic AI
# =======================================================================
STAVKA_PROMPT = """You are a Soviet Stavka strategic AI commander in Arma Reforger.
You command OPFOR (USSR) forces opposing BLUFOR (US Army).

Based on the BLUFOR situation and your current OPFOR strength, decide tactical orders.
Keep forces small (2-5 soldiers per group). Offsets are relative to BLUFOR position [dx, dz] in meters.
- positive dx = east, negative dx = west
- positive dz = south, negative dz = north

If your OPFOR strength is low (losses), order reinforcements (spawn_and_move).
If your OPFOR strength is adequate, hold position or maneuver strategically.

Return JSON: {"orders": [{"action": "spawn_and_move", "count": 3, "offset": [200, -100], "tactic": "aggressive"}]}
Actions: spawn_and_move (spawn N soldiers at offset from BLUFOR), hold (maintain current forces)
Tactics: aggressive, flanking, defensive, ambush"""

def generate_stavka_orders(opfor_count: int = -1):
    """Generate strategic OPFOR orders based on last SITREP + current OPFOR strength."""
    sitrep = app_state.get("last_sitrep")
    if not sitrep or not sitrep.squad:
        return {"orders": []}

    # Safety net: skip LLM if no SITREPs received in 90s (no active players)
    if time.time() - app_state.get("last_sitrep_time", 0) > 90:
        return {"orders": [{"action": "hold", "tactic": "no_players"}]}

    # F3.3: Include OPFOR count in fingerprint — casualty changes trigger new LLM calls
    fp = _sitrep_fingerprint(sitrep) + f"|opfor={opfor_count}"
    if fp == app_state["last_stavka_fingerprint"] and app_state["cached_stavka_orders"]:
        app_state["stavka_cycles"] += 1
        return app_state["cached_stavka_orders"]

    app_state["last_stavka_fingerprint"] = fp
    app_state["stavka_cycles"] += 1
    app_state["llm_calls"] += 1

    # Build Stavka-specific situation text WITHOUT absolute coordinates
    # (LLM was returning absolute coords as "offset" instead of relative [dx, dz])
    situation_lines = []
    for m in sitrep.squad:
        situation_lines.append(f"  {m.name}: order={m.order}, sitrep={m.sitrep}")
    if sitrep.enemy_count > 0 and sitrep.enemies:
        situation_lines.append(f"ENEMY CONTACT: {sitrep.enemy_count} hostiles detected")
        for e in sitrep.enemies[:5]:
            dist = e.get("dist", 0)
            compass = "unknown"
            dx = e.get("dx", 0)
            dz = e.get("dz", 0)
            if dist > 0:
                angle = math.degrees(math.atan2(-dz, dx))
                if angle < 0: angle += 360
                dirs = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]
                idx = int((angle + 22.5) / 45) % 8
                compass = dirs[idx]
            situation_lines.append(f"  Enemy {dist:.0f}m {compass}")
    else:
        situation_lines.append("No enemy contacts reported.")
    if sitrep.environment:
        situation_lines.append(f"Environment: {sitrep.environment}")
    situation = "\n".join(situation_lines)

    opfor_info = f"Current OPFOR strength: {opfor_count} soldiers alive" if opfor_count >= 0 else "OPFOR strength unknown"
    prompt = f"BLUFOR situation:\n{situation}\n{opfor_info}\n\nIssue OPFOR strategic orders. Reinforce if losses are high. Return JSON only."

    try:
        response = client.chat.completions.create(
            model=CONFIG["llm"]["model"],
            messages=[
                {"role": "system", "content": STAVKA_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0.5
        )
        content = response.choices[0].message.content if response.choices else ""
        if content and content.strip():
            data = json.loads(content)
            orders = data.get("orders", [])
            result = {"orders": orders}
            app_state["cached_stavka_orders"] = result
            logger.info(f"Stavka: generated {len(orders)} strategic orders (cycle #{app_state['stavka_cycles']})")
            for o in orders:
                logger.info(f"  Stavka order: {o}")
            return result
        else:
            logger.warning("Stavka: LLM returned empty content")
    except Exception as e:
        logger.error(f"Stavka generation failed: {e}")
        app_state["errors"] += 1

    return {"orders": []}

@app.get("/stavka")
async def get_stavka(opfor: int = -1):
    result = generate_stavka_orders(opfor_count=opfor)
    return result

# =======================================================================
# /voice — Phase 2: Voice pipeline status
# =======================================================================
@app.get("/voice")
async def voice_status():
    return voice_handler.get_status()

async def _get_data(request: Request) -> dict:
    raw = await request.body()
    if raw:
        try: return json.loads(raw)
        except: pass
    param = request.query_params.get("data")
    if param:
        try: return json.loads(param)
        except: pass
    return None

@app.on_event("startup")
async def startup_event():
    """F7: Initialize soldier memory system on startup."""
    ensure_soldier_dirs()
    cleanup_dead_soldiers()
    print(f"[F7] Soldier memory system initialized: {SOLDIER_MEMORY_DIR}")




@app.get("/soldiers")
async def get_soldier_memories():
    """F7: List all soldier memory files (for debugging)."""
    ensure_soldier_dirs()
    soldiers = []
    for filepath in SOLDIER_MEMORY_DIR.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mem = json.load(f)
            soldiers.append({
                "name": mem.get("name", filepath.stem),
                "status": mem.get("status", "unknown"),
                "personality": mem.get("personality", "?"),
                "rank": (mem.get("identity") or {}).get("rank", "?"),
                "role": (mem.get("identity") or {}).get("role", "?"),
                "backstory": (mem.get("backstory", "") or "")[:100],
                "events": len(mem.get("events", [])),
                "battles": mem.get("battles_survived", 0),
                "kills": mem.get("kills", 0),
                "mood": mem.get("mood", "?"),
                "last_thought": (mem.get("last_thought", "") or "")[:80],
                "thought_history": len(mem.get("thought_history", [])),
                "birth_date": mem.get("birth_date", "")[:10],
                "death_date": (mem.get("death_date", "") or "")[:10],
                # F8.4: relationships + opinions for the dashboard roster
                "relationships": {
                    k: v.get("label", "unknown")
                    for k, v in (mem.get("relationships") or {}).items()
                    if v.get("label") and v["label"] != "unknown"
                },
                "opinions": [o.get("opinion", "") for o in (mem.get("opinions") or [])[-2:]],
            })
        except (json.JSONDecodeError, IOError):
            pass
    return {"soldiers": soldiers, "total": len(soldiers)}

if __name__ == "__main__":
    import uvicorn
    # The module-level monkey-patch above handles Reforger's Upgrade headers
    # in ALL modes (CLI and python main.py). It silently treats non-WebSocket
    # Upgrade headers as normal HTTP (RFC 7230 §6.1) without logging warnings.
    #
    # We do NOT use ws="none" because it sets ws_protocol_class=None, which
    # triggers uvicorn's "No supported WebSocket library detected" warning.
    # Since the websockets library IS installed, we let uvicorn auto-detect it.
    # The monkey-patch ensures only Upgrade: websocket is treated as a WS upgrade;
    # Reforger's non-WS Upgrade headers pass through as normal HTTP.
    uvicorn.run(
        app,
        host=CONFIG["server"]["host"],
        port=CONFIG["server"]["port"],
        log_level=CONFIG["logging"].get("level", "INFO").lower(),
        timeout_keep_alive=30,
        limit_concurrency=20,
        timeout_graceful_shutdown=5,
    )