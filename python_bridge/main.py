"""
Reforger LLM Squad Control - Python Bridge
FastAPI server that bridges Arma Reforger with OpenAI-compatible LLM proxy.
"""

import json
import time
import logging
from typing import Optional
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
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

# Initialize OpenAI client with explicit timeout
client = OpenAI(
    base_url=CONFIG["llm"]["base_url"],
    api_key=CONFIG["llm"]["api_key"],
    timeout=float(CONFIG["llm"]["timeout_seconds"])
)

# --- Data Models ---

class SquadName(str, Enum):
    ALPHA = "ALPHA"
    BRAVO = "BRAVO"
    CHARLIE = "CHARLIE"

class Action(str, Enum):
    MOVE = "MOVE"
    SUPPRESS = "SUPPRESS"
    FLANK = "FLANK"
    RETREAT = "RETREAT"
    HOLD = "HOLD"

class SitRepRequest(BaseModel):
    """Squad telemetry sent from Reforger to Python"""
    squad: SquadName
    grid: str
    position_x: float
    position_y: float
    position_z: float
    health: float
    ammo_percent: float
    status: str
    nearby_enemies: int = 0
    timestamp: float = Field(default_factory=time.time)

class SitRepResponse(BaseModel):
    """Response back to Reforger"""
    status: str
    action: Action
    target_grid: Optional[str] = None
    voice_reply: str
    timestamp: float = Field(default_factory=time.time)

class CommandRequest(BaseModel):
    """Operator text command sent to LLM"""
    squad: SquadName
    operator_command: str
    current_situation: str = ""

# Function schema for LLM tool calling
ISSUE_ORDER_FUNCTION = {
    "name": "issue_order",
    "description": "Issue a tactical order to a squad based on the situation",
    "parameters": {
        "type": "object",
        "properties": {
            "squad": {"type": "string", "enum": ["ALPHA", "BRAVO", "CHARLIE"]},
            "action": {"type": "string", "enum": ["MOVE", "SUPPRESS", "FLANK", "RETREAT", "HOLD"]},
            "target_grid": {"type": "string"},
            "voice_reply": {"type": "string"}
        },
        "required": ["squad", "action", "voice_reply"]
    }
}

# --- System Prompt ---

SYSTEM_PROMPT = """You are a tactical AI adjutant in Arma Reforger.
You control squad units and issue orders based on the situation.

Current situation: {situation}

Given the operator's command and the current situation, issue a tactical order.
Respond ONLY with valid JSON matching the schema below.
No markdown, no extra text, just the JSON object."""

FUNCTION_CALLING_PROMPT = """You are a tactical AI adjutant in Arma Reforger.
You control squad units and issue orders based on the situation.

Operator command: {command}
Current situation: {situation}

Issue a tactical order. Respond ONLY with valid JSON matching the schema.
No markdown, no extra text, just the JSON object."""

# --- State ---

app_state = {
    "last_sitrep": None,
    "health_check_time": time.time(),
    "llm_calls": 0,
    "errors": 0,
    "last_status": None,
    "last_waypoint": None
}

# --- API Functions ---

def get_situation_text(sitrep: SitRepRequest) -> str:
    """Convert SITREP to human-readable text for LLM"""
    return (
        f"Squad {sitrep.squad.value} at grid {sitrep.grid}, "
        f"position ({sitrep.position_x:.1f}, {sitrep.position_y:.1f}, {sitrep.position_z:.1f}). "
        f"Health: {sitrep.health:.0f}%, Ammo: {sitrep.ammo_percent:.0f}%. "
        f"Status: {sitrep.status}. "
        f"Nearby enemies: {sitrep.nearby_enemies}. "
        f"Last update: {sitrep.timestamp:.0f}s ago."
    )

def call_llm_with_function_calling(command: str, situation: str) -> SitRepResponse:
    """Call LLM with function calling for structured output"""
    try:
        app_state["llm_calls"] += 1
        
        messages = [
            {"role": "system", "content": FUNCTION_CALLING_PROMPT.format(
                command=command, situation=situation
            )},
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
        
        # Parse function call
        tool_call = response.choices[0].message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        
        return SitRepResponse(
            status="ok",
            action=Action(args["action"]),
            target_grid=args.get("target_grid", ""),
            voice_reply=args.get("voice_reply", f"Squad {args['squad']}, {args['action']} confirmed."),
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"LLM function calling error: {e}")
        app_state["errors"] += 1
        return SitRepResponse(
            status="error",
            action=Action.HOLD,
            voice_reply=f"Command timeout ({CONFIG['llm']['timeout_seconds']}s), holding position.",
            timestamp=time.time()
        )

def call_llm_json_mode(command: str, situation: str) -> SitRepResponse:
    """Fallback: call LLM with JSON mode"""
    try:
        app_state["llm_calls"] += 1
        
        response = client.chat.completions.create(
            model=CONFIG["llm"]["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(situation=situation)},
                {"role": "user", "content": command}
            ],
            response_format={"type": "json_object"},
            max_tokens=CONFIG["llm"]["max_tokens"],
            temperature=0.3
        )
        
        content = response.choices[0].message.content
        data = json.loads(content)
        
        return SitRepResponse(
            status="ok",
            action=Action(data["action"]),
            target_grid=data.get("target_grid", ""),
            voice_reply=data.get("voice_reply", ""),
            timestamp=time.time()
        )
        
    except Exception as e:
        logger.error(f"LLM JSON mode error: {e}")
        app_state["errors"] += 1
        return SitRepResponse(
            status="error",
            action=Action.HOLD,
            voice_reply=f"Command timeout ({CONFIG['llm']['timeout_seconds']}s), holding position.",
            timestamp=time.time()
        )

# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    logger.info("=== Reforger LLM Bridge Starting ===")
    logger.info(f"Proxy URL: {CONFIG['llm']['base_url']}")
    logger.info(f"Model: {CONFIG['llm']['model']}")
    logger.info(f"Port: {CONFIG['server']['port']}")
    
    # Test proxy connection
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
    description="HTTP bridge between Arma Reforger and OpenAI-compatible LLM",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    """Health endpoint - pinged by Reforger at startup"""
    uptime = time.time() - app_state["health_check_time"]
    return {
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
        "llm_calls": app_state["llm_calls"],
        "errors": app_state["errors"],
        "proxy": CONFIG["llm"]["base_url"],
        "model": CONFIG["llm"]["model"]
    }

@app.post("/sitrep")
async def receive_sitrep(sitrep: SitRepRequest):
    """Receive SITREP from Reforger, return action command"""
    app_state["last_sitrep"] = sitrep
    logger.info(f"Received SITREP: Squad {sitrep.squad.value}, grid {sitrep.grid}")
    
    situation = get_situation_text(sitrep)
    
    # Try function calling first, fallback to JSON mode
    try:
        response = call_llm_with_function_calling(
            command=f"Squad {sitrep.squad.value} at {sitrep.grid}: {sitrep.status}",
            situation=situation
        )
    except:
        logger.info("Function calling failed, using JSON mode")
        response = call_llm_json_mode(
            command=f"Squad {sitrep.squad.value} at {sitrep.grid}: {sitrep.status}",
            situation=situation
        )
    
    logger.info(f"LLM Response: action={response.action}, reply={response.voice_reply}")
    return response

@app.post("/command")
async def receive_command(request: CommandRequest):
    """Receive operator command, return LLM action"""
    logger.info(f"Command: Squad {request.squad.value} - {request.operator_command}")
    
    situation = request.current_situation if request.current_situation else "No situation data available."
    
    try:
        response = call_llm_with_function_calling(
            command=request.operator_command,
            situation=situation
        )
    except:
        logger.info("Function calling failed, using JSON mode")
        response = call_llm_json_mode(
            command=request.operator_command,
            situation=situation
        )
    
    return response

@app.post("/command/text")
async def receive_text_command(request: CommandRequest):
    """Alias for /command but accepts text payload"""
    return await receive_command(request)

@app.post("/status")
async def receive_status(status: dict = None):
    """Receive status update from Reforger - POST version to match LLMBridge.c"""
    if status:
        logger.info(f"Status update from game: {status}")
        app_state["last_status"] = status
    return {"status": "ok", "timestamp": time.time()}

@app.get("/status")
async def get_status():
    """Get current bridge status"""
    return {
        "state": app_state,
        "config": "Loaded",  # Don't expose config details (contains API key)
        "last_sitrep": app_state["last_sitrep"].dict() if app_state["last_sitrep"] else None
    }

@app.post("/waypoint")
async def receive_waypoint(waypoint: dict = None):
    """Receive waypoint creation notification from Reforger"""
    if waypoint:
        logger.info(f"Waypoint created: {waypoint}")
        app_state["last_waypoint"] = waypoint
    return {"status": "ok", "timestamp": time.time()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=CONFIG["server"]["host"],
        port=CONFIG["server"]["port"],
        log_level=CONFIG["logging"].get("level", "INFO").lower()
    )
