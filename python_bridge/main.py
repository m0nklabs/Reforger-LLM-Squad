"""
Reforger LLM Squad Control - Python Bridge
FastAPI server that bridges Arma Reforger with OpenAI-compatible LLM proxy.

F1.3: Route sync complete. Game sends via GET ?data=<urlencoded_json>.
F2.3: Waypoint execution — LLM orders → AIWaypoint → squad moves.
F2.x: Live orders — /orders endpoint for real-time debugging without game restart.
"""

import json
import time
import logging
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, ConfigDict, field_validator
from openai import OpenAI

import os

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

# --- Pydantic Models ---

class SitRepMember(BaseModel):
    name: str = ""
    order: str = "HOLD"
    sitrep: str = "clear"

class SitRepRequest(BaseModel):
    source: str = "game"
    type: str = "SITREP"
    squad: List[SitRepMember] = []
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
            "action": {"type": "string", "enum": ["MOVE", "SUPPRESS", "FLANK", "RETREAT", "HOLD"]},
            "target_offset": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Relative offset [dx, dz] in meters from squad position."
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
Keep offsets 50-300m. No enemies nearby = HOLD with [0, 0]."""

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
}

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
    for m in sitrep.squad:
        lines.append(f"  {m.name}: order={m.order}, sitrep={m.sitrep}")
    return "Squad status:\n" + "\n".join(lines) if lines else "No squad data."

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
    return "|".join(parts)

def call_llm(command: str, situation: str) -> SitRepResponse:
    app_state["llm_calls"] += 1
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
Return JSON: {"thoughts": [{"name": "Alpha_1", "thought": "...", "mood": "..."}]}
Moods: alert, bored, nervous, confident, annoyed, scared, calm, excited."""

def assign_personalities(squad):
    """Assign stable personalities to squad members (deterministic by name)."""
    import hashlib
    for m in squad:
        if m.name not in app_state["ai_personalities"]:
            h = int(hashlib.md5(m.name.encode()).hexdigest(), 16)
            personality = PERSONALITIES[h % len(PERSONALITIES)]
            app_state["ai_personalities"][m.name] = personality

def generate_ai_thoughts():
    """Generate thoughts for all squad members based on last SITREP. One LLM call for all."""
    sitrep = app_state.get("last_sitrep")
    if not sitrep or not sitrep.squad:
        return {"thoughts": []}

    assign_personalities(sitrep.squad)

    # Dedup: skip LLM if situation unchanged
    fp = _sitrep_fingerprint(sitrep)
    if fp == app_state["last_thought_fingerprint"] and app_state["cached_thoughts"]:
        return app_state["cached_thoughts"]

    app_state["last_thought_fingerprint"] = fp
    app_state["thought_calls"] += 1

    # Build member descriptions
    member_lines = []
    for m in sitrep.squad:
        p = app_state["ai_personalities"].get(m.name, "STEADY")
        member_lines.append(f"- {m.name} ({p}): order={m.order}, sitrep={m.sitrep}")

    situation = get_situation_text(sitrep)
    members_text = "\n".join(member_lines)
    prompt = f"Situation:\n{situation}\n\nSquad members:\n{members_text}\n\nGenerate one thought per member."

    try:
        # Simple prompt — let model output plain text, parse line by line
        # 3B models struggle with complex JSON schemas, so keep it simple
        simple_prompt = f"""Generate one short thought (max 15 words) for each squad member based on their personality and the situation. 

Format each as: [Name] thought text

Squad members:
{members_text}

Situation: {situation}

Output:"""
        
        response = client.chat.completions.create(
            model=CONFIG["llm"]["model"],
            messages=[
                {"role": "system", "content": "You generate personality-driven thoughts for AI soldiers. Each member has a personality that shapes their thoughts. Be concise and in-character."},
                {"role": "user", "content": simple_prompt}
            ],
            max_tokens=200,
            temperature=0.8
        )
        
        content = response.choices[0].message.content if response.choices else ""
        if not content or not content.strip():
            logger.warning("AI thought: LLM returned empty content")
            return {"thoughts": []}
        
        # Parse plain text: [Name] thought text  OR  Name: thought
        thoughts = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Try [Name] thought format
            if "[" in line and "]" in line:
                b_start = line.index("[")
                b_end = line.index("]", b_start)
                name = line[b_start+1:b_end].strip()
                thought = line[b_end+1:].lstrip(":").strip().strip('"\'')
                # Clean name: strip "thought" suffix if model included it
                name = name.replace(" thought", "").strip()
                if name and thought:
                        thoughts.append({"name": name.strip(" -"), "thought": thought, "mood": "neutral"})
            elif ":" in line:
                colon_idx = line.index(":")
                name = line[:colon_idx].strip(" -")
                thought = line[colon_idx+1:].strip().strip('"\'')
                # Clean name: strip "thought" suffix
                name = name.replace(" thought", "").strip()
                if name and thought and len(name) < 20:
                    thoughts.append({"name": name, "thought": thought, "mood": "neutral"})
        
        if not thoughts:
            logger.warning(f"AI thought: could not parse thoughts from: {content[:100]}")
            return {"thoughts": []}
        
        result = {"thoughts": thoughts}
        app_state["cached_thoughts"] = result
        app_state["llm_calls"] += 1
        logger.info(f"AI thoughts generated: {len(thoughts)} thoughts for {len(sitrep.squad)} members")
        for t in thoughts:
            logger.info(f"  [{t['name']}] {t['thought'][:80]}")
        return result
    except Exception as e:
        logger.error(f"AI thought generation failed: {e}")
        app_state["errors"] += 1

    return {"thoughts": []}

# =======================================================================
# /ai_thought — F2.7: Individual AI Brains
# Game polls this endpoint to get thoughts for each AI squad member
# =======================================================================
async def lifespan(app: FastAPI):
    logger.info("=== Reforger LLM Bridge Starting ===")
    logger.info(f"Proxy URL: {CONFIG['llm']['base_url']}")
    logger.info(f"Model: {CONFIG['llm']['model']}")
    logger.info(f"Port: {CONFIG['server']['port']}")
    try:
        test_response = client.chat.completions.create(model=CONFIG["llm"]["model"], messages=[{"role": "user", "content": "Test"}], max_tokens=10)
        logger.info(f"Proxy connection OK: {test_response.model}")
    except Exception as e:
        logger.warning(f"Proxy connection failed: {e}")
    yield
    logger.info("=== Reforger LLM Bridge Shutting Down ===")

app = FastAPI(title="Reforger LLM Squad Control", version="2.0.0", lifespan=lifespan)

# =======================================================================
# GET /health
# =======================================================================
@app.get("/health")
async def health_check():
    uptime = time.time() - app_state["health_check_time"]
    return {
        "status": "healthy", "uptime_seconds": round(uptime, 2),
        "llm_calls": app_state["llm_calls"], "errors": app_state["errors"],
        "sitreps_received": app_state["sitrep_count"], "commands_received": app_state["command_count"],
        "pending_orders": len(app_state["pending_orders"]),
        "sitreps_skipped_llm": app_state.get("sitrep_skipped", 0),
        "proxy": CONFIG["llm"]["base_url"], "model": CONFIG["llm"]["model"]
    }

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
    logger.info(f"LLM order: action={response.action}, offset={response.target_offset}")
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
async def get_ai_thought():
    result = generate_ai_thoughts()
    return result

# =======================================================================
# F3.1: Stavka OPFOR strategic AI
# =======================================================================
STAVKA_PROMPT = """You are a Soviet Stavka strategic AI commander in Arma Reforger.
You command OPFOR (USSR) forces opposing BLUFOR (US Army).

Based on the BLUFOR situation, decide how to deploy OPFOR forces.
Keep forces small (2-5 soldiers per group). Offsets are relative to BLUFOR position [dx, dz] in meters.
- positive dx = east, negative dx = west
- positive dz = south, negative dz = north

Return JSON: {"orders": [{"action": "spawn_and_move", "count": 3, "offset": [200, -100], "tactic": "aggressive"}]}
Actions: spawn_and_move (spawn N soldiers at offset from BLUFOR), hold (maintain current forces)
Tactics: aggressive, flanking, defensive, ambush"""

def generate_stavka_orders():
    """Generate strategic OPFOR orders based on last SITREP."""
    sitrep = app_state.get("last_sitrep")
    if not sitrep or not sitrep.squad:
        return {"orders": []}

    # Dedup: skip if situation unchanged
    fp = _sitrep_fingerprint(sitrep)
    if fp == app_state["last_stavka_fingerprint"] and app_state["cached_stavka_orders"]:
        app_state["stavka_cycles"] += 1
        return app_state["cached_stavka_orders"]

    app_state["last_stavka_fingerprint"] = fp
    app_state["stavka_cycles"] += 1
    app_state["llm_calls"] += 1

    situation = get_situation_text(sitrep)
    prompt = f"BLUFOR situation:\n{situation}\n\nIssue OPFOR strategic orders. Return JSON only."

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
async def get_stavka():
    result = generate_stavka_orders()
    return result

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
