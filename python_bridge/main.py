"""
Reforger LLM Squad Control - Python Bridge
FastAPI server that bridges Arma Reforger with OpenAI-compatible LLM proxy.

F1.3 (2026-08-09): Route sync complete.
  - Game sends data via GET ?data=<urlencoded_json> (POST body doesn't transmit in Enforce)
  - All endpoints accept both GET (query param) and POST (body)
  - Pydantic models used for internal parsing only
"""

import json
import time
import logging
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, ConfigDict
from openai import OpenAI

# Load config
import os
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

# Configure logging
logging.basicConfig(
    level=getattr(logging, CONFIG["logging"]["level"]),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), CONFIG["logging"]["file"])),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("reforger_bridge")

# Initialize OpenAI client
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
    voice_reply: str = ""
    timestamp: float = Field(default_factory=time.time)

# LLM function schema
ISSUE_ORDER_FUNCTION = {
    "name": "issue_order",
    "description": "Issue a tactical order to a squad based on the situation",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["MOVE", "SUPPRESS", "FLANK", "RETREAT", "HOLD"]},
            "target_grid": {"type": "string"},
            "voice_reply": {"type": "string"}
        },
        "required": ["action", "voice_reply"]
    }
}

SYSTEM_PROMPT = """You are a tactical AI adjutant in Arma Reforger.
You control squad units and issue orders based on the situation.

{situation}

Given the operator's command and the current situation, issue a tactical order.
Respond ONLY with valid JSON matching the schema below.
No markdown, no extra text, just the JSON object."""

# --- State ---

app_state = {
    "last_sitrep": None,
    "health_check_time": time.time(),
    "llm_calls": 0,
    "errors": 0,
    "last_status": None,
    "last_waypoint": None,
    "sitrep_count": 0,
    "command_count": 0,
}

# --- Helpers ---

def get_situation_text(sitrep: SitRepRequest) -> str:
    lines = []
    for m in sitrep.squad:
        lines.append(f"  {m.name}: order={m.order}, sitrep={m.sitrep}")
    return "Squad status:\n" + "\n".join(lines) if lines else "No squad data."

def call_llm(command: str, situation: str) -> SitRepResponse:
    """Call LLM with function calling, fallback to JSON mode"""
    try:
        app_state["llm_calls"] += 1
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(situation=situation)},
            {"role": "user", "content": command}
        ]
        response = client.chat.completions.create(
            model=CONFIG["llm"]["model"],
            messages=messages,
            tools=[{"type": "function", "function": ISSUE_ORDER_FUNCTION}],
            tool_choice={"type": "function", "function": {"name": "issue_order"}},
            max_tokens=CONFIG["llm"]["max_tokens"],
            temperature=0.3
        )
        tool_call = response.choices[0].message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        return SitRepResponse(
            status="ok",
            action=args.get("action", "HOLD"),
            voice_reply=args.get("voice_reply", ""),
        )
    except Exception as e1:
        logger.warning(f"Function calling failed: {e1}")
        try:
            response = client.chat.completions.create(
                model=CONFIG["llm"]["model"],
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT.format(situation=situation)},
                    {"role": "user", "content": command + '\nReturn JSON: {"action": "HOLD|ATTACK|PATROL|RETREAT|SUPPRESS", "voice_reply": "..."}'}
                ],
                response_format={"type": "json_object"},
                max_tokens=CONFIG["llm"]["max_tokens"],
                temperature=0.3
            )
            data = json.loads(response.choices[0].message.content)
            return SitRepResponse(
                status="ok",
                action=data.get("action", "HOLD"),
                voice_reply=data.get("voice_reply", ""),
            )
        except Exception as e2:
            logger.error(f"LLM call failed: {e2}")
            app_state["errors"] += 1
            return SitRepResponse(status="error", action="HOLD", voice_reply="Command timeout, holding position.")

def extract_data(request: Request) -> dict:
    """Extract JSON data from request — tries body first, then ?data= query param"""
    # Try POST body
    import asyncio
    raw = asyncio.get_event_loop().run_until_complete(request.body())
    if raw:
        try:
            return json.loads(raw)
        except:
            pass
    # Try GET query param
    param = request.query_params.get("data")
    if param:
        try:
            return json.loads(param)
        except:
            pass
    return None

# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Reforger LLM Bridge Starting ===")
    logger.info(f"Proxy URL: {CONFIG['llm']['base_url']}")
    logger.info(f"Model: {CONFIG['llm']['model']}")
    logger.info(f"Port: {CONFIG['server']['port']}")

    try:
        test_response = client.chat.completions.create(
            model=CONFIG["llm"]["model"],
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=10
        )
        logger.info(f"Proxy connection OK: {test_response.model}")
    except Exception as e:
        logger.warning(f"Proxy connection failed: {e}")

    yield
    logger.info("=== Reforger LLM Bridge Shutting Down ===")

# --- FastAPI App ---

app = FastAPI(
    title="Reforger LLM Squad Control",
    version="1.3.0",
    lifespan=lifespan
)

# =======================================================================
# GET /health — pinged by LLMBridge at startup + every 15s if not ready
# =======================================================================
@app.get("/health")
async def health_check():
    uptime = time.time() - app_state["health_check_time"]
    return {
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
        "llm_calls": app_state["llm_calls"],
        "errors": app_state["errors"],
        "sitreps_received": app_state["sitrep_count"],
        "commands_received": app_state["command_count"],
        "proxy": CONFIG["llm"]["base_url"],
        "model": CONFIG["llm"]["model"]
    }

# =======================================================================
# /sitrep — GET (query param) or POST (body)
# Game sends: {"source":"game","type":"SITREP","squad":[{name,order,sitrep},...]}
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
        sitrep = SitRepRequest(squad=[
            SitRepMember(name=f"Alpha_{i+1}") for i in range(4)
        ])

    app_state["last_sitrep"] = sitrep
    logger.info(f"SITREP #{app_state['sitrep_count']}: {len(sitrep.squad)} members")

    situation = get_situation_text(sitrep)
    response = call_llm(
        command=f"SITREP review: {len(sitrep.squad)} squad members deployed.",
        situation=situation
    )
    logger.info(f"LLM order: action={response.action}, reply={response.voice_reply}")
    return response

# =======================================================================
# /command — GET (query param) or POST (body)
# Game sends: {"source":"game","type":"COMMAND","command":"ATTACK","model":"llama3"}
# Game's OnRestSuccess → OnRadioCallback(data) parses response for keywords
# =======================================================================
@app.get("/command")
@app.post("/command")
async def receive_command(request: Request):
    app_state["command_count"] += 1
    data = await _get_data(request)

    if data:
        try:
            cmd = CommandRequest(**data)
        except:
            cmd = CommandRequest(command="UNKNOWN")
    else:
        cmd = CommandRequest(command="UNKNOWN")

    logger.info(f"Command #{app_state['command_count']}: '{cmd.command}'")

    situation = get_situation_text(app_state["last_sitrep"]) if app_state["last_sitrep"] else "No SITREP data."
    response = call_llm(command=cmd.command, situation=situation)
    logger.info(f"LLM order: action={response.action}, reply={response.voice_reply}")
    return response

# =======================================================================
# /status — GET: if ?data= present → process, else return bridge state
#           POST: always process
# =======================================================================
@app.get("/status")
async def receive_status_get(request: Request):
    if request.query_params.get("data"):
        return await _process_status(request)
    # No data param → return bridge state
    last_sitrep = app_state["last_sitrep"].model_dump() if app_state["last_sitrep"] else None
    return {
        "state": {k: v for k, v in app_state.items() if k != "last_sitrep"},
        "last_sitrep": last_sitrep,
        "config_loaded": True
    }

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
# /waypoint — GET (query param) or POST (body)
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
# Helper: extract JSON from request (body or query param)
# =======================================================================
async def _get_data(request: Request) -> dict:
    raw = await request.body()
    if raw:
        try:
            return json.loads(raw)
        except:
            pass
    param = request.query_params.get("data")
    if param:
        try:
            return json.loads(param)
        except:
            pass
    return None

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=CONFIG["server"]["host"],
        port=CONFIG["server"]["port"],
        log_level=CONFIG["logging"].get("level", "INFO").lower()
    )
