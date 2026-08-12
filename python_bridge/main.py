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
import traceback
import re
import random
import asyncio
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
    identity: str = ""  # A.4: in-game identity from SCR_CharacterIdentityComponent (name+alias)
    alive: bool = True   # B.1: game reports a dead member via alive=false (default True: today's SITREPs don't send it)

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
# NOTE: absolute paths based on this file's location — a relative path like
# Path("ai_soldiers") depends on the CWD (bridge started from python_bridge/,
# but dev-loop pi runs from the repo root and would create a stray folder).
_BRIDGE_DIR = Path(__file__).resolve().parent
SOLDIER_MEMORY_DIR = _BRIDGE_DIR / "ai_soldiers"
SOLDIER_GRAVEYARD_DIR = _BRIDGE_DIR / "ai_soldiers" / "graveyard"
SOLDIER_RETENTION_DAYS = 7  # Keep dead soldier files for 7 days
REPORTS_DIR = _BRIDGE_DIR / "reports"  # B.5: after-action reports
ORDERS_BACKLOG_FILE = _BRIDGE_DIR / "pending_orders.json"  # D.3: orders survive bridge restarts

def ensure_soldier_dirs():
    """Create soldier memory directories if they don't exist."""
    SOLDIER_MEMORY_DIR.mkdir(exist_ok=True)
    SOLDIER_GRAVEYARD_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)


# ─── B.4: Fatigue & session memory ────────────────────────────────────
# Long sessions degrade soldiers: fatigue level rises with elapsed session
# time and combat intensity (CONTACT/CRITICAL events accelerate it), drifts
# rested moods toward tired/worn, and is fed into prompts so the LLM
# roleplays the strain. At session end the after-action report persists a
# deployment recap into each soldier's memory file (previous_deployments)
# + reports/last_summary.json, so the squad remembers previous deployments
# ACROSS bridge restarts (B.5's app_state-only summary was lost on restart).

FATIGUE_LABELS = {0: "fresh", 1: "tired", 2: "exhausted", 3: "combat-worn"}
# Rested moods drift under fatigue; event-driven moods (nervous/alert/scared)
# are left alone - fear wins over exhaustion.
FATIGUE_DRIFT_MOODS = {"calm", "steady", "confident", "neutral", ""}


def _fatigue_cfg(key, default):
    return (CONFIG.get("fatigue") or {}).get(key, default)


def _compute_fatigue() -> dict:
    """B.4: session fatigue from elapsed time + combat intensity.
    Returns {"level": 0..3, "label": str, "minutes": float}."""
    if not _fatigue_cfg("enabled", True):
        return {"level": 0, "label": "fresh", "minutes": 0.0}
    minutes = max(0.0, (time.time() - app_state.get("session_start_time", time.time())) / 60.0)
    level = 0
    if minutes >= _fatigue_cfg("worn_minutes", 75):
        level = 3
    elif minutes >= _fatigue_cfg("exhausted_minutes", 45):
        level = 2
    elif minutes >= _fatigue_cfg("tired_minutes", 20):
        level = 1
    # Combat intensity accelerates fatigue: sustained contact or CRITICALs
    # (downed leader, casualties) wear the squad faster than time alone.
    battle_log = app_state.get("battle_log", [])
    criticals = sum(1 for e in battle_log if "CRITICAL" in e)
    contacts = sum(1 for e in battle_log if "CONTACT" in e)
    if criticals >= _fatigue_cfg("combat_acceleration_events", 3) or contacts >= _fatigue_cfg("contact_acceleration_events", 5):
        level = min(3, level + 1)
    return {"level": level, "label": FATIGUE_LABELS[level], "minutes": round(minutes, 1)}


def update_soldier_fatigue(squad) -> dict:
    """B.4: persist current fatigue into each alive member's memory file.
    Writes only when the fatigue LEVEL changes (coarse, so file churn is
    rare). Drifts a rested mood toward tired/worn at high fatigue, but
    leaves event-driven moods (nervous/alert) untouched.
    Returns the current squad fatigue dict (for prompt injection)."""
    fatigue = _compute_fatigue()
    for m in squad:
        if not m.alive:
            continue
        mem = load_soldier_memory(m.name)
        prev_level = (mem.get("fatigue") or {}).get("level", 0)
        if prev_level == fatigue["level"]:
            continue
        mem["fatigue"] = dict(fatigue)
        mood = mem.get("mood", "neutral")
        if fatigue["level"] >= 2 and mood in FATIGUE_DRIFT_MOODS:
            mem["mood"] = "tired" if fatigue["level"] == 2 else "worn"
        save_soldier_memory(m.name, mem)
        logger.info(f"[B.4] {m.name} fatigue -> {fatigue['label']} ({fatigue['minutes']:.0f} min)")
    return fatigue


# ─── C.2: Radio chatter layer ─────────────────────────────────────────
# During quiet periods (session active, no recent contacts, no pending
# orders) the squad randomly "talks" over the radio via TTS — short patrol
# lines from a pool, voiced by a random squad member. Pure audio ambience;
# deliberately NOT written to soldier memory files (background noise, not
# conversation). The gating decision lives in _chatter_due() (pure, unit
# tested); _chatter_loop() is the asyncio task driving it.

CHATTER_LINES = [
    "{name}, all callsigns — sector's quiet, keep your eyes open.",
    "{name}, holding position, waiting on orders.",
    "{name}, anyone got eyes on the treeline?",
    "{name}, ammo check — I'm good over here.",
    "{name}, nice and steady, watch your spacing.",
    "{name}, did a sweep of the area, nothing moving.",
    "{name}, stay sharp, could be lurkers out here.",
    "{name}, copy all. Radio discipline, everyone.",
]

CHATTER_BATTLE_MARKERS = ("CONTACT", "CRITICAL", "DOWN")


def _battle_event_age_seconds(log_entry: str) -> float:
    """Age of a battle-log entry (parses the [HH:MM:SS] prefix).
    Events from a previous day (negative age) count as old: clamp high."""
    m = re.match(r"\[(\d{2}):(\d{2}):(\d{2})\]", log_entry)
    if not m:
        return 0.0
    lt = time.localtime()
    evt = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                       int(m.group(1)), int(m.group(2)), int(m.group(3)), 0, 0, -1))
    age = time.time() - evt
    if age < 0:
        return 3600.0  # yesterday's event: long ago
    return age


def _chatter_member() -> str:
    """Random ALIVE squad member from the last SITREP (fallback Alpha_1..5)."""
    sitrep = app_state.get("last_sitrep")
    names = []
    if sitrep and sitrep.squad:
        names = [m.name for m in sitrep.squad if m.alive]
    if not names:
        names = [f"Alpha_{i}" for i in range(1, 6)]
    return random.choice(names)


def _chatter_line() -> tuple:
    """A random chatter line + the speaker's name (name formatted for TTS)."""
    name = _chatter_member()
    line = random.choice(CHATTER_LINES).format(name=name.replace("_", " "))
    return line, name


def _chatter_due(now: float = None) -> tuple:
    """C.2: (due, reason) — should the chatter loop speak right now?
    Pure decision function so the gating rules are unit-testable."""
    now = now if now is not None else time.time()
    if not tts_handler.enabled:
        return False, "tts_disabled"
    if (now - app_state.get("last_sitrep_time", 0)) > 90:
        return False, "no_session"
    if now < app_state.get("chatter_next_at", 0):
        return False, "not_yet"
    if app_state.get("pending_orders"):
        return False, "orders_pending"
    quiet = float((CONFIG.get("chatter") or {}).get("quiet_seconds", 30))
    for e in app_state.get("battle_log", []):
        if any(t in e for t in CHATTER_BATTLE_MARKERS):
            if _battle_event_age_seconds(e) < quiet:
                return False, "recent_battle"
    return True, "quiet"


async def _chatter_loop():
    """C.2: background task — speak radio chatter during quiet periods."""
    cfg = CONFIG.get("chatter") or {}
    if not cfg.get("enabled", True):
        logger.info("[C.2] Radio chatter disabled in config")
        return
    if not tts_handler.enabled:
        logger.info("[C.2] Radio chatter disabled: TTS not enabled")
        return
    min_int = float(cfg.get("min_interval_seconds", 45))
    max_int = float(cfg.get("max_interval_seconds", 150))
    max_per_session = int(cfg.get("max_per_session", 12))
    logger.info(f"[C.2] Radio chatter loop started (every {min_int:.0f}-{max_int:.0f}s while quiet)")
    while True:
        await asyncio.sleep(5)
        try:
            now = time.time()
            due, reason = _chatter_due(now)
            if not due:
                # No session: re-arm for a fresh session so the squad does not
                # chatter the moment someone connects.
                if reason == "no_session":
                    app_state["chatter_next_at"] = now + random.uniform(min_int, max_int)
                continue
            if app_state.get("chatter_count", 0) >= max_per_session:
                app_state["chatter_next_at"] = now + 3600  # stay silent till next session
                continue
            line, name = _chatter_line()
            tts_handler.speak(line, member_index=_name_hash(name, "voice") % 10, member_name=name)
            app_state["chatter_count"] = app_state.get("chatter_count", 0) + 1
            app_state["last_chatter"] = {"text": line[:80], "time": now, "member": name}
            app_state["chatter_next_at"] = now + random.uniform(min_int, max_int)
            logger.info(f"[C.2] Chatter #{app_state['chatter_count']} ({name}): {line[:60]}...")
        except Exception as e:
            logger.warning(f"[C.2] chatter loop error: {e}")
            app_state["errors"] = app_state.get("errors", 0) + 1


# ─── B.5: After-action report ──────────────────────────────────────────
# When a session ends (SITREP gap > SESSION_GAP_SECONDS), write a battle
# report to reports/ and keep a one-line summary to feed into the NEXT
# session's soldier prompts ("the squad remembers the previous deployment").

def _write_after_action_report() -> str:
    """B.5: snapshot the session that just ended into a battle report.

    Reads all soldier memory files (alive + graveyard) + the battle log.
    Writes reports/report_<ts>.json. Returns a compact summary line that is
    stored in app_state and fed into the next session's prompts.
    Only called from _check_session_boundary() when a session actually ran.
    """
    ensure_soldier_dirs()
    soldiers = []
    for filepath in sorted(SOLDIER_MEMORY_DIR.glob("*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mem = json.load(f)
            ident = mem.get("identity") or {}
            soldiers.append({
                "name": mem.get("name", filepath.stem),
                "rank": ident.get("rank", "?"),
                "role": ident.get("role", "?"),
                "status": mem.get("status", "?"),
                "kills": mem.get("kills", 0),
                "battles": mem.get("battles_survived", 0),
                "mood": mem.get("mood", "?"),
                "last_thought": (mem.get("last_thought") or "")[:200],
            })
        except (json.JSONDecodeError, IOError):
            pass
    kia = []
    for filepath in sorted(SOLDIER_GRAVEYARD_DIR.glob("*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mem = json.load(f)
            ident = mem.get("identity") or {}
            kia.append({
                "name": mem.get("name", filepath.stem),
                "rank": ident.get("rank", "?"),
                "kills": mem.get("kills", 0),
                "battles": mem.get("battles_survived", 0),
                "death_date": (mem.get("death_date") or "")[:16],
            })
        except (json.JSONDecodeError, IOError):
            pass

    if not soldiers and not kia:
        logger.info("[B.5] Session ended with no soldier memory - no report written")
        return ""
    started = app_state.get("session_start_time", app_state.get("health_check_time"))
    duration_min = max(0, round((time.time() - started) / 60, 1))
    report = {
        "session_end": datetime.now().isoformat(),
        "session_duration_minutes": duration_min,
        "battle_log": app_state.get("battle_log", [])[-15:],
        "soldiers": soldiers,
        "kia": kia,
    }
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"report_{ts}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"[B.5] After-action report written: {path}")
    except IOError as e:
        logger.warning(f"[B.5] report write failed: {e}")
        return ""

    # Compact summary line for the next session's prompts
    total_kills = sum(s.get("kills", 0) for s in soldiers)
    total_battles = sum(s.get("battles", 0) for s in soldiers)
    returned = sum(1 for s in soldiers if s.get("status") == "alive")
    lost = len(kia)
    parts = [f"{len(soldiers)} soldiers deployed, {returned} returned, {lost} KIA"]
    if kia:
        parts.append("fell: " + ", ".join(f"{k['name']} ({k['kills']} kills)" for k in kia))
    parts.append(f"squad totals: {total_kills} kills, {total_battles} battles")
    summary = "; ".join(parts)
    app_state["last_report_summary"] = summary
    app_state["last_report_path"] = str(path)

    # B.4: persist the recap so it survives bridge restarts, and store a
    # per-soldier copy in each alive member's memory file (the squad
    # "remembers" its previous deployment). Reset fatigue for the next session.
    try:
        with open(REPORTS_DIR / "last_summary.json", "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "written": datetime.now().isoformat()}, f, ensure_ascii=False)
    except IOError as e:
        logger.warning(f"[B.4] last_summary.json write failed: {e}")
    deploy_entry = {"date": datetime.now().strftime("%Y-%m-%d"), "summary": summary}
    for filepath in SOLDIER_MEMORY_DIR.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mem = json.load(f)
            if mem.get("status") != "alive":
                continue
            deploys = mem.get("previous_deployments") or []
            if not deploys or deploys[-1].get("summary") != summary:
                deploys.append(deploy_entry)
                mem["previous_deployments"] = deploys[-3:]  # remember last 3 deployments
            mem["fatigue"] = {"level": 0, "label": "fresh", "minutes": 0.0}
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(mem, f, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, IOError):
            pass
    return summary


def _load_last_report_summary() -> str:
    """B.4: load the persisted deployment recap (survives bridge restarts)."""
    path = REPORTS_DIR / "last_summary.json"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("summary", "")
    except (json.JSONDecodeError, IOError):
        return ""

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
        # A.1: full conversation log (user situation briefs + assistant thoughts),
        # last 10 exchanges (20 messages). Feeds per-soldier LLM conversations.
        "conversation": [],
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


def _base_rank(name: str) -> str:
    """B.2: the deterministic (hash-derived) rank a soldier starts at.
    Promotions update identity.rank; a replacement starts over at base."""
    return RANKS[_name_hash(name, "rank") % len(RANKS)]


# ─── B.2: Rank progression ────────────────────────────────────────────
# Deeds -> promotion. score = kills*2 + battles_survived*3. Thresholds per
# rank index (index 0 = PVT, 4 = SGT): reaching a threshold promotes one
# rank. Changes identity (prompt voice) + squadmate opinions. Death resets.
RANK_SCORE_THRESHOLDS = [0, 4, 8, 12, 16]  # PFC=4, SPC=8, CPL=12, SGT=16


def _deeds_score(mem: dict) -> int:
    return mem.get("kills", 0) * 2 + mem.get("battles_survived", 0) * 3


def check_rank_progression(name: str) -> str:
    """B.2: promote a soldier if their deeds passed the next rank threshold(s).
    Returns the new rank (or "" if unchanged). Deeds are cumulative - a single
    check promotes as far as the score allows. Updates identity + event log
    + battle memory. Caller nudges squadmate opinions on promotion."""
    mem = load_soldier_memory(name)
    if mem.get("status") != "alive":
        return ""
    identity = mem.get("identity")
    if not identity:
        ensure_soldier_identity(name)
        mem = load_soldier_memory(name)
        identity = mem.get("identity", {})
    try:
        idx = RANKS.index(str(identity.get("rank", "PVT")))
    except ValueError:
        idx = 0
    score = _deeds_score(mem)
    # Promote as far as the score allows (max SGT)
    while idx < len(RANKS) - 1 and score >= RANK_SCORE_THRESHOLDS[idx + 1]:
        idx += 1
    new_rank = RANKS[idx]
    if new_rank == identity.get("rank"):
        return ""  # no promotion
    identity["rank"] = new_rank
    mem["identity"] = identity
    save_soldier_memory(name, mem)
    log_soldier_event(name, "promotion", f"Promoted to {new_rank} after {mem.get('kills', 0)} kill(s) and {mem.get('battles_survived', 0)} battle(s)")
    add_battle_event("ORDER", f"{name} promoted to {new_rank}")
    logger.info(f"[B.2] {name} promoted to {new_rank} (score {score})")
    return new_rank


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
    mem["conversation"] = mem.get("conversation", [])  # A.1: migrate old files
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
    name = sanitize_soldier_name(name)
    mem = load_soldier_memory(name)
    mem["last_thought"] = thought
    mem["mood"] = mood or mem.get("mood", "neutral")
    hist = mem.get("thought_history", [])
    hist.append({"time": datetime.now().isoformat(), "thought": thought})
    mem["thought_history"] = hist[-10:]  # rolling window of 10
    save_soldier_memory(name, mem)


def log_soldier_exchange(name: str, thought: str, mood: str, situation_brief: str):
    """A.1: Store a full user->assistant exchange in the soldier's conversation.

    Keeps thought_history (dashboard view) AND the new conversation log
    (real chat turns for per-soldier LLM prompts). Rolling: last 10
    exchanges = 20 messages.
    """
    name = sanitize_soldier_name(name)
    mem = load_soldier_memory(name)
    mem["last_thought"] = thought
    mem["mood"] = mood or mem.get("mood", "neutral")
    hist = mem.get("thought_history", [])
    hist.append({"time": datetime.now().isoformat(), "thought": thought})
    mem["thought_history"] = hist[-10:]  # rolling window of 10
    conv = mem.get("conversation", [])
    conv.append({"role": "user", "content": situation_brief})
    conv.append({"role": "assistant", "content": thought, "mood": mem["mood"]})
    mem["conversation"] = conv[-20:]  # last 10 exchanges
    save_soldier_memory(name, mem)



def get_squadmate_recent_thoughts(sitrep, self_name: str, max_mates: int = 4) -> str:
    """A.2: Most recent transmission from each squadmate (from their memory).

    Reads the last assistant message in each squadmate's conversation log
    (fallback: thought_history for older files). Used so soldiers can react
    to EACH OTHER's words, not just to the situation. Excludes self.
    Returns a compact multi-line string ("- Name (mood): \"...\"") or ""
    when nobody has spoken yet (first cycle).
    """
    lines = []
    for m in sitrep.squad:
        if m.name == self_name:
            continue
        mem = load_soldier_memory(m.name)
        thought = ""
        mood = ""
        conv = mem.get("conversation", [])
        # Last assistant message = their most recent words
        for msg in reversed(conv):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                thought = str(msg.get("content", ""))[:120]
                mood = str(msg.get("mood", ""))[:20]
                break
        if not thought:
            hist = mem.get("thought_history", [])
            if hist:
                thought = str(hist[-1].get("thought", ""))[:120]
                mood = str(mem.get("mood", ""))[:20]
        if thought:
            mood_suffix = f" ({mood})" if mood and mood != "neutral" else ""
            lines.append(f"- {m.name}{mood_suffix}: \"{thought}\"")
        if len(lines) >= max_mates:
            break
    return "\n".join(lines)


def sanitize_soldier_name(name: str) -> str:
    """Strip rank prefixes the LLM sometimes prepends ("CPL Alpha_1" -> "Alpha_1").
    Keeps the canonical callsign so memory files stay consistent."""
    name = (name or "").strip()
    # Known rank tokens that may prefix a callsign
    for token in ("PVT ", "PFC ", "SPC ", "CPL ", "SGT ", "SSG "):
        if name.startswith(token):
            return name[len(token):].strip()
    return name


# ─── B.1: Death detection tuning ────────────────────────────────────────
# A member is only marked dead when the bridge has SOLID evidence:
# 1. CONFIRMED: the game reports "alive": false for the member (SITREP field).
# 2. MISSING: the member is absent from death_grace_cycles consecutive thought
#    cycles. The grace period prevents FALSE KIA during transient squad gaps
#    (respawn re-link per rule 52, despawn -> re-spawn rebuilds).
DEATH_GRACE_CYCLES = int(CONFIG.get("game", {}).get("death_grace_cycles", 2))
# A SITREP gap longer than this means the player disconnected / a new session
# started. Members of the OLD session must not be treated as dead just because
# the new session's squad doesn't include them.
SESSION_GAP_SECONDS = 90

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


def _soldier_voice_index(name: str) -> int:
    """F8.9: Map a soldier name (Alpha_1..Alpha_5) to a TTS voice index."""
    try:
        idx = int(name.split("_")[-1]) - 1
        return max(0, idx % 5)
    except (ValueError, IndexError):
        return 0


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
        # F8.9: Speak the contact report with the soldier's voice
        tts_handler.speak(f"Contact! {count} hostiles, {distance} meters, {direction}!", member_index=_soldier_voice_index(name))
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
        _persist_pending_orders()  # D.3
        result += f" -> MEDIC order queued for {target}"
        # F8.9: Audible medic call with the soldier's voice
        tts_handler.speak(f"Medic! {target} is down! Medic!", member_index=_soldier_voice_index(name))
        logger.info(f"[TOOL] {result}")

    elif tool_name == "suggest_tactic":
        formation = args.get("formation", "Line")
        direction = args.get("direction", "")
        add_battle_event("ORDER", f"{name} suggests {formation} formation" + (f" heading {direction}" if direction else ""))
        # C.5: tactic suggestions go to the CO (dashboard) for APPROVAL instead
        # of auto-executing - the player stays in command. On approval the
        # formation order is queued for the game.
        sid = app_state.get("suggestion_counter", 0) + 1
        app_state["suggestion_counter"] = sid
        app_state.setdefault("pending_suggestions", []).append({
            "id": sid,
            "time": time.strftime("%H:%M:%S"),
            "soldier": name,
            "formation": formation,
            "direction": direction,
            "status": "pending",
        })
        result += f" -> {formation} formation suggested to CO for approval"
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
    "promotion": ("respect", +2, "earned a promotion"),  # B.2: squad notices
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
        # Materialize/refresh opinions from current scores (keep latest 6)
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
            if not best or abs(score) < 4:
                continue
            lbl, template = best
            # Update existing opinion if its strength label changed
            updated = False
            for o in opinions:
                if o.get("topic") == other:
                    if o.get("strength") != lbl:
                        o["opinion"] = template.format(subject=other)
                        o["strength"] = lbl
                        o["score"] = score
                        updated = True
                    break
            if not updated and other not in opinion_topics:
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
            if not isinstance(entry, dict):  # drift guard: old files may store bare strings
                continue
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
    "session_start_time": time.time(),  # B.5: when the current session began
    "session_had_members": False,       # B.5: any SITREP with a squad this session
    "last_report_summary": None,        # B.5: previous deployment recap for prompts
    "last_report_path": None,           # B.5: most recent report file
    "fatigue": {"level": 0, "label": "fresh", "minutes": 0.0},  # B.4: current squad fatigue
    # C.2: radio chatter layer (ambience TTS during quiet periods)
    "chatter_count": 0,             # chatter utterances this session
    "last_chatter": None,           # {"text", "time", "member"}
    "chatter_next_at": 0.0,         # earliest next chatter time
    "chatter_task": None,           # asyncio task handle (avoid GC)
    # F5: Battle Memory — rolling event log for LLM context
    "battle_log": [],                # last 15 events, included in LLM prompts
    "last_leader_state": "alive",
    "last_enemy_count": -1,   # F8.5: previous SITREP enemy count (kill attribution)
    "kill_rotation": 0,       # F8.5: round-robin kill attribution index
    "last_squad_names": [],  # Track squad member names for death detection
    "soldier_memory_enabled": True,    # F6: track leader state changes
    # E.3: rolling trace of the last 10 bridge errors (source + traceback),
    # exposed via /health for diagnosis without digging through logs
    "recent_errors": [],
    # C.5: soldier tactic suggestions awaiting CO approval (dashboard)
    "pending_suggestions": [],
    "suggestion_counter": 0,
}

# ─── D.3: pending_orders backlog persistence ───────────────────────────

def _persist_pending_orders():
    """D.3: save the live orders queue to disk so it survives bridge restarts.
    Called after every queue mutation (append / pop). The queue is tiny
    (the game drains it every 2s), so writing the whole list is cheap."""
    try:
        with open(ORDERS_BACKLOG_FILE, "w", encoding="utf-8") as f:
            json.dump(app_state.get("pending_orders", []), f, indent=2)
    except IOError as e:
        logger.warning(f"[D.3] pending_orders persist failed: {e}")


def _load_pending_orders():
    """D.3: restore the orders queue persisted by a previous bridge process."""
    try:
        if ORDERS_BACKLOG_FILE.exists():
            with open(ORDERS_BACKLOG_FILE, "r", encoding="utf-8") as f:
                backlog = json.load(f)
            if isinstance(backlog, list):
                restored = [o for o in backlog if isinstance(o, dict)]
                app_state["pending_orders"] = restored
                if restored:
                    logger.info(f"[D.3] Restored {len(restored)} pending order(s) from backlog")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[D.3] backlog load failed: {e}")


def _record_error(source: str, exc: BaseException):
    """E.3: count a bridge error AND keep a rolling trace (last 10) of
    source + message + short traceback. /health exposes them so failures
    can be diagnosed without digging through bridge.log.
    Must be called from inside an except block (or with a constructed
    exception for parse failures)."""
    app_state["errors"] += 1
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=3))
    errs = app_state.setdefault("recent_errors", [])
    errs.append({
        "time": time.strftime("%H:%M:%S"),
        "source": source,
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": tb,
    })
    app_state["recent_errors"] = errs[-10:]
    logger.error(f"[ERROR:{source}] {type(exc).__name__}: {exc}")


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
        # B.1: mark confirmed-dead members for the adjutant (they are still
        # listed in the SITREP with alive=false). The LLM should know the
        # squad is down a soldier - but the dead do not have mood/thoughts.
        mem = load_soldier_memory(m.name)
        if not m.alive:
            lines.append(f"  {m.name}: [KIA - confirmed dead]")
            continue
        # F8.7: Include soldier mood + last thought so the adjutant LLM
        # (which issues orders) knows how the squad feels, not just positions.
        mood = mem.get("mood", "")
        last_thought = (mem.get("last_thought") or "")[:80]
        base = f"  {m.name}: order={m.order}, sitrep={m.sitrep}"
        if mood and mood != "neutral":
            base += f", mood={mood}"
        if last_thought:
            base += f", thinking=\"{last_thought}\""
        lines.append(base)
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

    # B.4: squad fatigue — long sessions wear the squad; the adjutant should
    # account for it when ordering moves/engagements.
    fatigue = _compute_fatigue()
    if fatigue["level"] > 0:
        lines.append(f"Squad fatigue: {fatigue['label']} after {fatigue['minutes']:.0f} min of combat — reduced endurance, slower reactions.")

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
        parsed = json.loads(text)
        # Contract: only dicts are valid here. A bare JSON string/array
        # ("Alpha_1: ..." or ["..."]) means the LLM didn't emit an object -
        # return None so callers take their fallback path instead of crashing.
        return parsed if isinstance(parsed, dict) else None
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
        data = extract_json_block(content)
        if not data:
            logger.error(f"LLM returned unparseable JSON: {content[:100]!r}")
            return SitRepResponse(status="ok", action="HOLD", target_offset=None, voice_reply="")
        to = data.get("target_offset", None)
        if isinstance(to, str):
            try: to = json.loads(to)
            except: to = None
        return SitRepResponse(status="ok", action=data.get("action", "HOLD"), target_offset=to, voice_reply=data.get("voice_reply", ""))
    except Exception as e2:
        _record_error("call_llm", e2)
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

The squad leader (CO) is the PLAYER. Soldiers refer to them as "CO" or "sir" and wait for orders.

When the situation is quiet/clear, members may chat with squadmates naturally.
When in combat, thoughts should be tactical and urgent.

CRITICAL: Do NOT repeat or paraphrase your own earlier thoughts (shown below).
Each thought must be NEW — react to the CURRENT situation and what changed since last time.

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

# ─── A.1: Per-soldier conversations ────────────────────────────────────
# Each soldier gets ONE private LLM conversation: a system prompt with their
# own identity + backstory + chain of command, their own thought history as
# real chat turns, and the current situation as the latest user turn.

PERSONALITY_DESCRIPTIONS = {
    "AGGRESSIVE": "wants to attack, push forward, impatient",
    "CAUTIOUS": "worried about ambushes, wants cover, overwatch",
    "JOKER": "cracks jokes, lightens the mood, doesn't take things seriously",
    "VETERAN": "calm, experienced, tactical observations",
    "ROOKIE": "nervous, eager to prove themselves, asks questions",
    "STEADY": "professional, focused, mission-oriented",
}

AI_THOUGHT_SYSTEM_PROMPT_SOLO = """You are {identity}, a soldier in an Arma Reforger squad.
Backstory: {backstory}
Personality: {personality} - {personality_desc}

The squad leader (CO) is the PLAYER. Refer to them as "CO" or "sir"; you wait for their orders.

You are shown the current tactical situation and your own recent thoughts (your private
conversation log). Produce ONE new thought (max 15 words) in character: react to what is
happening NOW and what CHANGED since your last thought. A veteran sounds different from a
rookie; your role shapes what you notice.

CRITICAL: Do NOT repeat or paraphrase your own earlier thoughts. Each thought must be NEW.

You also hear your squadmates' most recent radio transmissions (included in the situation
as "Squadmate chatter"). React to them when it matters: acknowledge, answer, reassure,
or push back - real soldiers talk to each other, not just to the situation.

You may also see "Your last action's result": what happened after your previous tool call
(order queued, report logged, medic requested). Learn from it - if it worked, keep doing
it; if it didn't, adjust. Never mention the result text itself.

OPTIONAL tool (only call when the situation genuinely warrants action - most of the time omit it):
- report_contact(direction, distance, count): enemy sighting, report to squad
- report_clear(): area is clear
- request_orders(): ask CO for new orders
- report_status(health, ammo): report own condition
- call_medic(target): request medical help for a downed squadmate
- suggest_tactic(formation, direction): formation: Column/Line/Wedge/Diamond, direction: N/E/S/W/NE/NW/SE/SW

Return JSON only: {{"thought": "...", "mood": "alert|bored|nervous|confident|annoyed|scared|calm|excited", "tool": {{"name": "...", "args": {{...}}}}}}
The "tool" field is optional - omit it when no action is needed."""

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

    # ─── B.1: Replacement soldier detection ────────────────────────────
    # A member whose memory file says "dead" reappeared in the SITREP as
    # ALIVE (alive=true / no alive field): the game spawned a replacement
    # with the same callsign. Resurrect the file and record the legacy the
    # new soldier inherits. A member still reported alive=false is NOT a
    # replacement - they are simply still dead (skip, no resurrect/re-kill
    # churn every cycle).
    for m in sitrep.squad:
        if not m.alive:
            continue
        mem = load_soldier_memory(m.name)
        if mem.get("status") == "dead":
            death_date = str(mem.get("death_date") or "unknown")[:10]
            kills = mem.get("kills", 0)
            battles = mem.get("battles_survived", 0)
            mem["status"] = "alive"
            mem["death_date"] = None
            mem["legacy"] = (
                f"The previous {m.name} was KIA on {death_date} with {kills} confirmed kill(s) "
                f"after {battles} battle(s). The squad remembers them - you are filling their boots."
            )
            # B.2: a replacement starts fresh - base rank, no kills/battles.
            # The predecessor's stats live on in the legacy string above.
            identity = mem.get("identity") or {}
            identity["rank"] = _base_rank(m.name)
            mem["identity"] = identity
            mem["kills"] = 0
            mem["battles_survived"] = 0
            save_soldier_memory(m.name, mem)
            log_soldier_event(m.name, "replacement", f"Replacement soldier takes over {m.name} - predecessor KIA")
            add_battle_event("ORDER", f"Replacement soldier arrived for {m.name}")
            logger.info(f"[B.1] {m.name} is a replacement - legacy recorded")

    # ─── Death detection: two evidence signals ────────────────────────
    # 1. CONFIRMED: game reports "alive": false for a member -> dead now.
    # 2. MISSING: absent from DEATH_GRACE_CYCLES consecutive thought cycles.
    #    (Grace prevents false KIA during transient gaps: respawn re-link
    #    per rule 52, despawn -> re-spawn rebuilds, partial SITREPs.)
    last_names = set(app_state.get("last_squad_names", []))
    missing = app_state.setdefault("missing_soldiers", {})
    # A member that is back with us was never gone (reset their counter)
    for name in list(missing.keys()):
        if name in current_names:
            missing.pop(name, None)
    # Increment counters for everyone known to the session who is absent now.
    # "known" = previous cycle's squad UNION already-missing members (a member
    # who dropped out of last_squad_names must still accumulate absence).
    known = last_names | set(missing.keys())
    for name in known - current_names:
        missing[name] = missing.get(name, 0) + 1
    dead_soldiers = {m.name for m in sitrep.squad if not m.alive} | {
        name for name, cycles in missing.items() if cycles >= DEATH_GRACE_CYCLES
    }
    for dead_name in sorted(dead_soldiers):
        # Dedup guard: a member marked dead in an earlier cycle (and who may
        # still appear with alive=false) must not be re-archived / re-grieved.
        dead_mem = load_soldier_memory(dead_name)
        if dead_mem.get("status") == "dead":
            missing.pop(dead_name, None)
            continue
        mark_soldier_dead(dead_name)
        # B.1: archive final stats to the graveyard at the moment of death
        dead_mem = load_soldier_memory(dead_name)
        archive_path = SOLDIER_GRAVEYARD_DIR / f"{dead_name}.json"
        try:
            with open(archive_path, "w", encoding="utf-8") as f:
                json.dump(dead_mem, f, indent=2, ensure_ascii=False)
            logger.info(f"[B.1] {dead_name} archived to graveyard (kills={dead_mem.get('kills', 0)}, battles={dead_mem.get('battles_survived', 0)})")
        except IOError as e:
            logger.warning(f"[B.1] graveyard archive failed for {dead_name}: {e}")
        missing.pop(dead_name, None)
        # Log to surviving soldiers: grief event + relationship + opinion
        # (skip the fallen themselves - their file is already archived)
        for m in sitrep.squad:
            if m.name == dead_name:
                continue
            log_soldier_event(m.name, "teammate_kia", f"{dead_name} was killed in action")
            survivor = load_soldier_memory(m.name)
            survivor["relationships"] = survivor.get("relationships", {})
            survivor["relationships"][dead_name] = {"score": 6, "label": "mourned"}
            survivor["opinions"] = survivor.get("opinions", [])
            opinion = {"topic": f"fallen:{dead_name}", "opinion": f"They mourn {dead_name} - fought alongside them, now they are gone"}
            if opinion not in survivor["opinions"]:
                survivor["opinions"].append(opinion)
            save_soldier_memory(m.name, survivor)
    
    app_state["last_squad_names"] = list(current_names)
    
    # F8.4: Update social bonds/opinions from this shared event
    # (alive members only - dead ones must keep the "mourned" relationship)
    alive_names = [m.name for m in sitrep.squad if m.alive]
    update_social_bonds(event, alive_names)

    # B.2: Rank progression - deeds earn promotions. Squadmates notice
    # (promotion nudge on relationships/opinions).
    promoted = [check_rank_progression(name) for name in alive_names]
    if any(promoted):
        update_social_bonds("promotion", alive_names)
    
    # Cleanup old dead soldier files
    cleanup_dead_soldiers()

    # Dedup: still use fingerprint but event changes it
    fp = _sitrep_fingerprint(sitrep) + "|event=" + event
    if fp == app_state["last_thought_fingerprint"] and app_state["cached_thoughts"] and event == "":
        return app_state["cached_thoughts"]

    app_state["last_thought_fingerprint"] = fp
    app_state["thought_calls"] += 1

    # ─── Build shared situation + event context ────────────────────────
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

    # ─── A.1: per-soldier LLM conversations (ONE private conversation per
    # soldier: identity+backstory+CoC system prompt, own thought history as
    # real chat turns, current situation as the latest turn). Falls back to
    # the batched single-call path if per-soldier generation is disabled or
    # no soldier produced a thought.
    thoughts = []
    if CONFIG.get("llm", {}).get("per_soldier_thoughts", True):
        thoughts = _generate_thoughts_per_soldier(sitrep, situation, event_context)
    if not thoughts:
        thoughts = _generate_thoughts_batched(sitrep, situation, event_context)
    if not thoughts:
        return {"thoughts": []}

    result = {"thoughts": thoughts}
    app_state["cached_thoughts"] = result
    # A.1: store each soldier's thought in their personal conversation history
    # (thought_history + conversation log). F8.3: process optional tool calls.
    event_brief = event_context.strip().splitlines()[0][:120] if event_context.strip() else "CONTEXT: routine situation"
    for t in thoughts:
        if not isinstance(t, dict):  # drift guard: LLM emitted a non-object entry
            continue
        tname = sanitize_soldier_name(t.get("name", "?"))
        tthought = t.get("thought", "")
        tmood = t.get("mood", "neutral")
        member = next((m for m in sitrep.squad if m.name == tname), None)
        brief = event_brief
        if member:
            brief += f" | your status: order={member.order}, sitrep={member.sitrep}"
        chatter = get_squadmate_recent_thoughts(sitrep, tname)  # A.2: keep chatter in the log
        if chatter:
            heard = " ; ".join(l.strip("- ").strip() for l in chatter.splitlines())[:180]
            brief += f" | heard: {heard}"
        log_soldier_exchange(tname, tthought, tmood, brief)
        tool = t.get("tool")
        if isinstance(tool, dict) and tool.get("name"):
            tool_result = handle_soldier_tool(tname, tool)  # NOT "result" - would clobber the return dict
            if tool_result:
                # A.3: store the consequence so the NEXT prompt shows the soldier
                # what their action actually did (order queued / event logged).
                mem = load_soldier_memory(tname)
                mem["last_tool_result"] = tool_result
                save_soldier_memory(tname, mem)
    logger.info(f"AI thoughts generated: {len(thoughts)} thoughts for {len(sitrep.squad)} members")
    for t in thoughts:
        name = t.get("name", "?")
        thought = t.get("thought", "")[:80]
        mood = t.get("mood", "?")
        logger.info(f"  [{name} ({mood})] {thought}")
    return result


def _generate_thoughts_batched(sitrep, situation, event_context):
    """F2.7 fallback: single shared-conversation LLM call for the whole squad.
    Used when per-soldier generation is disabled or produced no thoughts."""
    # Build member descriptions WITH identity + personal memory + conversation history
    member_lines = []
    for m in sitrep.squad:
        # B.1: dead members (alive=false) do not generate thoughts
        if not m.alive:
            continue
        p = app_state["ai_personalities"].get(m.name, "STEADY")
        identity = get_soldier_identity_summary(m.name)
        backstory = get_soldier_backstory(m.name)
        history = get_soldier_history_summary(m.name, max_events=5)
        own_thoughts = get_soldier_thought_history(m.name)
        social = get_social_summary(m.name)  # F8.4: relationships + opinions
        chatter = get_squadmate_recent_thoughts(sitrep, m.name)  # A.2
        mem = load_soldier_memory(m.name)
        last_result = mem.get("last_tool_result")  # A.3
        legacy = mem.get("legacy")  # B.1
        prev_deploy = app_state.get("last_report_summary")  # B.5
        # B.4: per-soldier previous deployments (personal memory) + fatigue
        own_deploys = mem.get("previous_deployments") or []
        fatigue = mem.get("fatigue") or _compute_fatigue()
        deploy_line = ""
        if own_deploys:
            deploy_line = "Previous deployments (personal memory): " + "; ".join(
                f"{d.get('date', '?')}: {d.get('summary', '')}" for d in own_deploys[-3:]
            )
        elif prev_deploy:
            deploy_line = f"Previous deployment (what the squad remembers): {prev_deploy}"
        fatigue_line = ""
        if fatigue.get("level", 0) > 0:
            fatigue_line = f"  Physical state: {fatigue['label']} after {fatigue.get('minutes', 0):.0f} min in the field\n"
        member_lines.append(
            f"- {identity}\n  Personality: {p}\n  Backstory: {backstory}\n{history}\n"
            f"{social}\n"
            f"  Own recent thoughts:\n{own_thoughts}\n"
            + (f"  Squadmate chatter heard:\n{chatter}\n" if chatter else "")
            + (f"  Last action result: {last_result}\n" if last_result else "")
            + (f"  Legacy: {legacy}\n" if legacy else "")
            + (deploy_line + "\n" if deploy_line else "")
            + fatigue_line
            + f"  Current: order={m.order}, sitrep={m.sitrep}"
        )

    members_text = "\n".join(member_lines)
    prompt = (
        f"Situation:\n{situation}\n{event_context}\n"
        f"Squad members (with identity, backstory and personal history):\n{members_text}\n\n"
        "Generate one thought per member reacting to the situation. The thought should reflect "
        "their rank, role, backstory AND their personal experiences. A veteran who has survived "
        "5 battles sounds different from a rookie on their first day. A medic thinks about wounds, "
        "a grenadier about angles. Stay in character.\n"
        "Members may ALSO react to what their squadmates said recently (shown as 'Squadmate chatter heard').\n\n"
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
        if not data:
            logger.warning(f"Batched thoughts: unparseable LLM output: {content[:100]!r}")
            return []
        thoughts = data.get("thoughts", data) if isinstance(data, dict) else data
        if not isinstance(thoughts, list):
            thoughts = []
        # Drift guard: drop non-object entries (proxy sometimes emits strings)
        thoughts = [t for t in thoughts if isinstance(t, dict)]
        app_state["llm_calls"] += 1
        return thoughts
    except Exception as e:
        _record_error("thoughts_batched", e)
        return []


def _generate_thoughts_per_soldier(sitrep, situation, event_context):
    """A.1: one private LLM conversation per soldier.

    messages = [soldier system prompt (identity + backstory + personality +
    CoC + tool rules)] + [own conversation history as real chat turns] +
    [current situation as the latest user turn]. One LLM call per soldier.
    Returns a list of thought dicts {"name", "thought", "mood", "tool"}.
    """
    event_brief = event_context.strip().splitlines()[0][:120] if event_context.strip() else "CONTEXT: routine situation"
    thoughts = []
    # B.1: dead members (alive=false) do not generate thoughts
    live_members = [m for m in sitrep.squad if m.alive]
    for m in live_members:
        name = m.name
        mem = ensure_soldier_identity(name)
        p = mem.get("personality") or app_state["ai_personalities"].get(name, "STEADY")
        identity = get_soldier_identity_summary(name)
        backstory = get_soldier_backstory(name)
        social = get_social_summary(name)
        system_content = AI_THOUGHT_SYSTEM_PROMPT_SOLO.format(
            identity=identity,
            backstory=backstory,
            personality=p,
            personality_desc=PERSONALITY_DESCRIPTIONS.get(p, ""),
        )
        if social:
            system_content += "\n\nSquad social context:\n" + social
        if m.identity:
            # A.4: real in-game identity (from SCR_CharacterIdentityComponent.
            # GetFormattedFullName on the game side) - grounds the persona in
            # what the character is actually named in the world.
            system_content += "\n\nIn-game identity (military records): " + m.identity
        legacy = mem.get("legacy")
        if legacy:
            # B.1: replacement soldier - carries the predecessor's memory
            system_content += f"\n\nLegacy: {legacy}"
        prev_deploy = app_state.get("last_report_summary")
        own_deploys = mem.get("previous_deployments") or []
        if own_deploys:
            # B.4: this soldier's OWN memory of previous deployments
            deploy_lines = "; ".join(
                f"{d.get('date', '?')}: {d.get('summary', '')}" for d in own_deploys[-3:]
            )
            system_content += f"\n\nYour previous deployments (personal memory): {deploy_lines}"
        elif prev_deploy:
            # B.5: fallback — the squad remembers the previous deployment
            system_content += f"\n\nPrevious deployment (what the squad remembers): {prev_deploy}"
        # B.4: physical state — fatigue from this session's length + combat
        fatigue = mem.get("fatigue") or _compute_fatigue()
        if fatigue.get("level", 0) > 0:
            system_content += (
                f"\n\nYour physical state: {fatigue['label']} after {fatigue.get('minutes', 0):.0f} "
                f"min in the field — you feel it in your reactions and temper. "
                f"Let the strain show in your thoughts."
            )

        # Own conversation history (last 6 exchanges = 12 messages) as real chat turns
        conv = [c for c in mem.get("conversation", []) if isinstance(c, dict) and c.get("role")]
        history = conv[-12:]

        # A.2: squadmate chatter - their most recent words from the previous cycle
        chatter = get_squadmate_recent_thoughts(sitrep, name)
        user_content = (
            f"[NOW] {event_brief}\n\n"
            f"{situation}\n"
            f"Your status: order={m.order}, sitrep={m.sitrep}"
        )
        if chatter:
            user_content += (
                f"\n\nSquadmate chatter (their most recent words - react if it matters):\n"
                f"{chatter}"
            )
        # A.3: consequence of the soldier's last tool call ("your action did X")
        last_result = mem.get("last_tool_result")
        if last_result:
            user_content += f"\n\nYour last action's result: {last_result}"
        try:
            response = client.chat.completions.create(
                model=CONFIG["llm"]["model"],
                messages=[{"role": "system", "content": system_content}] + history + [{"role": "user", "content": user_content}],
                response_format={"type": "json_object"},
                max_tokens=300,
                temperature=0.7
            )
            content = response.choices[0].message.content if response.choices else ""
            data = extract_json_block(content)
            if not data:
                logger.warning(f"[A.1] {name}: unparseable thought output: {content[:100]!r}")
                continue
            # Accept a bare thought object OR an old-style {"thoughts": [...]} wrapper.
            # Drift guard: the proxy sometimes wraps plain TEXT in the list
            # ({"thoughts": ["Alpha_1: ..."]}) — salvage the string as the thought.
            obj = data
            if isinstance(data.get("thoughts"), list) and data["thoughts"]:
                obj = data["thoughts"][0]
            if isinstance(obj, str):
                obj = {"thought": obj}
            if not isinstance(obj, dict) or not obj.get("thought"):
                logger.warning(f"[A.1] {name}: no thought text in output: {content[:100]!r}")
                continue
            claimed = sanitize_soldier_name(obj.get("name", name)) or name
            if claimed != name:
                logger.warning(f"[A.1] LLM claimed to be '{claimed}' while generating for {name} - attributing to {name}")
            thoughts.append({
                "name": name,
                "thought": str(obj.get("thought", ""))[:200],
                "mood": str(obj.get("mood", "neutral"))[:20],
                "tool": obj.get("tool") if isinstance(obj.get("tool"), dict) else None,
            })
            app_state["llm_calls"] += 1
        except Exception as e:
            _record_error(f"thought_{name}", e)
    return thoughts

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
        "tts_enabled": tts_handler.enabled,
        # B.4: session length + fatigue for quick operator checks
        "session_minutes": round((time.time() - app_state.get("session_start_time", time.time())) / 60, 1),
        "fatigue": _compute_fatigue().get("label", "fresh"),
        # E.3: last bridge exceptions (source, message, short traceback)
        "recent_errors": app_state.get("recent_errors", [])[-5:],
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
    status = tts_handler.get_status()
    # C.2: chatter layer status for the dashboard / operator checks
    last_chatter = app_state.get("last_chatter") or {}
    status["chatter"] = {
        "enabled": bool((CONFIG.get("chatter") or {}).get("enabled", True)) and tts_handler.enabled,
        "count": app_state.get("chatter_count", 0),
        "last": last_chatter.get("text", ""),
        "last_member": last_chatter.get("member", ""),
        "last_age": round(time.time() - last_chatter["time"], 1) if last_chatter.get("time") else None,
    }
    return status

# =======================================================================
# /orders — LIVE command queue (F2.x: debug without game restart)
# POST /orders  {cmd: "spawn"} or {cmd: "move", offset: [100, 0]} or {cmd: "hold"}
# GET /orders   — returns first pending order, or {cmd: null}
# =======================================================================
@app.get("/orders")
async def get_orders():
    if app_state["pending_orders"]:
        order = app_state["pending_orders"].pop(0)
        _persist_pending_orders()  # D.3: keep backlog on disk in sync
        logger.info(f"Order delivered to game: {order}")
        return order
    return {"cmd": None}

@app.post("/orders")
async def post_orders(request: Request):
    data = await _get_data(request)
    if data:
        app_state["pending_orders"].append(data)
        _persist_pending_orders()  # D.3
        logger.info(f"Order queued: {data}")
        return {"status": "ok", "queued": len(app_state["pending_orders"])}
    return {"status": "error", "msg": "no data"}

# =======================================================================
# /sitrep — GET (query param) or POST (body)
# =======================================================================
def _check_session_boundary(now: float = None) -> bool:
    """Detect a new game session and reset squad state.

    A SITREP gap longer than SESSION_GAP_SECONDS means the player disconnected
    (no SITREPs are sent while nobody is in the session). When they reconnect,
    the new session's squad must be treated as a fresh one - members of the
    previous session must NOT be marked dead just because they are absent.
    Without this, a reconnect with a different squad composition would
    false-KIA everyone who didn't come back.

    B.5: when a session with soldiers actually ends, an after-action report
    is written first (squad state is still intact at this point)."""
    now = now or time.time()
    prev = app_state.get("last_sitrep_time", now)
    # NOTE: called from receive_sitrep BEFORE sitrep_count is incremented, so
    # the first SITREP ever sees count==0 (no boundary), and the SECOND SITREP
    # sees count==1 - which is the earliest point a gap is measurable.
    if app_state["sitrep_count"] > 0 and (now - prev) > SESSION_GAP_SECONDS:
        # A session with soldiers is ending - snapshot it before resetting.
        # Gate on session_had_members (set by receive_sitrep), NOT on
        # last_squad_names (only updated by thought cycles - a session with
        # SITREPs but no thoughts yet would silently lose its report).
        if app_state.get("session_had_members"):
            _write_after_action_report()
        app_state["last_squad_names"] = []
        app_state["missing_soldiers"] = {}
        app_state["session_had_members"] = False
        # C.2: chatter budget belongs to one session
        app_state["chatter_count"] = 0
        app_state["last_chatter"] = None
        logger.info("Session boundary detected (SITREP gap > 90s) - squad state reset")
        return True
    return False

@app.get("/sitrep")
@app.post("/sitrep")
async def receive_sitrep(request: Request):
    # B.1: if the previous SITREP is more than a session gap old, a new game
    # session started - forget the old session's squad (before updating the
    # timestamp so the gap is measurable).
    if _check_session_boundary():
        app_state["session_start_time"] = time.time()
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
    # B.4: track squad fatigue (session length + combat intensity). Runs even
    # when the LLM is skipped below, so memory files stay current.
    app_state["fatigue"] = update_soldier_fatigue(sitrep.squad)
    if sitrep.squad:
        app_state["session_had_members"] = True  # B.5: this session had a squad

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
            data = extract_json_block(content)
            if not data:
                logger.warning(f"Stavka: unparseable LLM output: {content[:80]!r}")
                _record_error("stavka_unparseable", ValueError(content[:80]))
                return {"orders": []}
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
        _record_error("stavka", e)

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

def _approve_suggestion(s: dict):
    """C.5: CO approved a soldier's tactic suggestion -> queue the real order."""
    s["status"] = "approved"
    app_state["pending_orders"].append({
        "cmd": "formation",
        "formation": s.get("formation", "Line"),
        "source": f"soldier:{s.get('soldier')} (CO approved)",
    })
    _persist_pending_orders()  # D.3
    add_battle_event("ORDER", f"CO approved {s.get('soldier')}'s suggestion: {s.get('formation')} formation")
    logger.info(f"[C.5] Suggestion #{s.get('id')} APPROVED by CO -> formation order queued")


# =======================================================================
# /suggestions — C.5: soldier tactic suggestions awaiting CO approval
# GET  /suggestions                -> all suggestions (pending + recent)
# POST /suggestions {"id": 1, "action": "accept"|"reject"}
# POST /suggestions {"action": "accept_all"}
# =======================================================================
@app.get("/suggestions")
async def get_suggestions():
    return {"suggestions": app_state.get("pending_suggestions", [])}

@app.post("/suggestions")
async def post_suggestions(request: Request):
    data = await _get_data(request)
    if not data:
        return {"status": "error", "msg": "no data"}
    action = data.get("action", "")
    suggestions = app_state.setdefault("pending_suggestions", [])
    if action == "accept_all":
        accepted = [s for s in suggestions if s.get("status") == "pending"]
        for s in accepted:
            _approve_suggestion(s)
        _trim_suggestions()
        return {"status": "ok", "accepted": len(accepted)}
    sid = data.get("id")
    for s in suggestions:
        if s.get("id") == sid:
            if action == "accept":
                _approve_suggestion(s)
            elif action == "reject":
                s["status"] = "rejected"
                add_battle_event("ORDER", f"CO rejected {s.get('soldier')}'s suggestion ({s.get('formation')})")
                logger.info(f"[C.5] Suggestion #{sid} REJECTED by CO")
            else:
                return {"status": "error", "msg": f"unknown action: {action}"}
            _trim_suggestions()
            return {"status": "ok", "suggestion": s}
    return {"status": "error", "msg": f"suggestion {sid} not found"}


def _trim_suggestions():
    """Keep all pending suggestions + the 5 most recent decided ones."""
    sugs = app_state.get("pending_suggestions", [])
    pending = [s for s in sugs if s.get("status") == "pending"]
    decided = [s for s in sugs if s.get("status") != "pending"][-5:]
    app_state["pending_suggestions"] = pending + decided


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
    # B.4: restore the previous deployment recap across bridge restarts
    persisted = _load_last_report_summary()
    if persisted:
        app_state["last_report_summary"] = persisted
        logger.info(f"[B.4] Restored last deployment recap: {persisted[:80]}...")
    print(f"[F7] Soldier memory system initialized: {SOLDIER_MEMORY_DIR}")

    # Phase 2 fix: wire up + start the voice pipeline (was configured but
    # never started — on_transcription stayed None, start() never called).
    def _on_voice_transcription(text: str):
        """PTT release → transcription → LLM order → queue for the game."""
        text = text.strip()
        if not text:
            return
        logger.info(f"[VOICE] Transcription: {text}")
        try:
            situation = get_situation_text(app_state["last_sitrep"]) if app_state.get("last_sitrep") else "No SITREP data."
            response = call_llm(command=text, situation=situation)
            order = {"cmd": response.action.lower(), "source": "voice", "voice_text": text}
            if response.target_offset and len(response.target_offset) == 2:
                order["offset"] = response.target_offset
            app_state["pending_orders"].append(order)
            _persist_pending_orders()  # D.3
            logger.info(f"[VOICE] Order queued: {order}")
            if response.voice_reply:
                tts_handler.speak(response.voice_reply, member_index=0)
        except Exception as e:
            _record_error("voice_order", e)

    voice_handler._on_transcription = _on_voice_transcription
    if voice_handler.enabled:
        started = voice_handler.start()
        logger.info(f"Voice handler start result: {started}")

    # Phase 3 fix: TTS was configured but never started (start() never called,
    # so speak() short-circuited on _running=False and ALL squad audio was silent).
    tts_handler.start()

    # D.3: restore orders queued before a bridge restart (the game drains
    # /orders every 2s, so a restart mid-queue would silently drop orders).
    _load_pending_orders()

    # C.2: start the radio chatter loop (background ambience TTS)
    app_state["chatter_next_at"] = time.time() + 30.0
    app_state["chatter_task"] = asyncio.create_task(_chatter_loop())




@app.get("/soldiers")
async def get_soldier_memories(detail: int = 0):
    """F7: List all soldier memory files. ?detail=1 includes full events/thoughts."""
    ensure_soldier_dirs()
    soldiers = []
    for filepath in SOLDIER_MEMORY_DIR.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mem = json.load(f)
            entry = {
                "name": mem.get("name", filepath.stem),
                "status": mem.get("status", "unknown"),
                "personality": mem.get("personality", "?"),
                "rank": (mem.get("identity") or {}).get("rank", "?"),
                "role": (mem.get("identity") or {}).get("role", "?"),
                "age": (mem.get("identity") or {}).get("age", "?"),
                "origin": (mem.get("identity") or {}).get("origin", "?"),
                "deployments": (mem.get("identity") or {}).get("deployments", 0),
                "backstory": (mem.get("backstory", "") or ""),
                "events": len(mem.get("events", [])),
                "battles": mem.get("battles_survived", 0),
                "kills": mem.get("kills", 0),
                "mood": mem.get("mood", "?"),
                "fatigue": (mem.get("fatigue") or {}).get("label", "fresh"),  # B.4
                "fatigue_minutes": (mem.get("fatigue") or {}).get("minutes", 0),  # B.4
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
            }
            # F8.10: Full detail mode for the dashboard soldier panel
            if detail:
                entry["event_log"] = [
                    {"t": e.get("time", "")[-8:-3], "type": e.get("type", "?"), "desc": e.get("desc", "")}
                    for e in (mem.get("events") or [])[-15:]
                ]
                entry["thought_log"] = [
                    h.get("thought", "") for h in (mem.get("thought_history") or [])[-10:]
                ]
            soldiers.append(entry)
        except (json.JSONDecodeError, IOError):
            pass
    # F8.8: Include archived KIA soldiers from the graveyard
    graveyard = []
    for filepath in SOLDIER_GRAVEYARD_DIR.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mem = json.load(f)
            graveyard.append({
                "name": mem.get("name", filepath.stem),
                "rank": (mem.get("identity") or {}).get("rank", "?"),
                "role": (mem.get("identity") or {}).get("role", "?"),
                "kills": mem.get("kills", 0),
                "battles": mem.get("battles_survived", 0),
                "death_date": (mem.get("death_date", "") or "")[:10],
            })
        except (json.JSONDecodeError, IOError):
            pass
    return {"soldiers": soldiers, "total": len(soldiers), "graveyard": graveyard}

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