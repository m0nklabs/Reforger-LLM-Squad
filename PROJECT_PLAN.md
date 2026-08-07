# PROJECT PLAN: Reforger LLM Squad Control

## Document Status
- **Created**: 2026-08-06
- **Author**: Goose AI Agent
- **Status**: DRAFT — Pending operator approval

---

## 1. PROJECT OVERVIEW

### 1.1 Doel
Bouw een LLM-powered squad control systeem voor Arma Reforger dat de operator in staat stelt om via natuurlijke taal (tekst in fase 1, spraak in fase 2) een AI-squad aan te sturen, en waarbij squadleden autonomoom observaties en statusupdates terugreporteren.

### 1.2 Architectuur
```
┌─────────────────────────────────────────────────────────────────────┐
│                        OPERATOR (you)                                │
│  Start game met -mod parameter  |  Start python_bridge/main.py      │
└──────────────┬──────────────────────────────┬───────────────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────┐    ┌───────────────────────────────────┐
│   Arma Reforger (Game)   │    │     Python Bridge (FastAPI)       │
│                          │    │         port 5000                  │
│  Enforce Script:         │    │                                   │
│  ┌─────────────────────┐ │    │  ┌─────────┐  ┌──────────────┐    │
│  │ LLMBridgeComponent  │◄├─────►│/health  │  │ /command     │    │
│  │  • Collect SITREP   │ │    │  │/sitrep  │  │ /voice (P2)  │    │
│  │  • POST to Python   │ │    │  └─────────┘  └──────┬───────┘    │
│  │  • Execute waypoint │ │    │                       │            │
│  │  • Radio callbacks  │ │    │                       ▼            │
│  └─────────────────────┘ │    │              ┌──────────────┐     │
│                          │    │              │ OpenAI SDK   │     │
└──────────────────────────┘    │              │ (function    │     │
                                │              │  calling)    │     │
                                │              └──────┬───────┘     │
                                └─────────────────────┼─────────────┘
                                                       │
                                       ┌───────────────▼───────────────┐
                                       │  Jouw Proxy (192.168.1.35)    │
                                       │  OpenAI-compatible API        │
                                       │  port 11434                   │
                                       └───────────────┬───────────────┘
                                                       │
                                       ┌───────────────▼───────────────┐
                                       │  llama-server (backend)       │
                                       │  Local LLM inference          │
                                       └───────────────────────────────┘
```

### 1.3 Data Flow
1. **Game → Python**: Enforce Script verzamelt squad telemetry (posities, health, ammo, enemies) en stuurt deze als JSON via HTTP POST naar `localhost:5000/sitrep`
2. **Python → LLM**: Python stuurt de situatie + operator commando naar de proxy via OpenAI function calling
3. **LLM → Python**: LLM retourneert gestructureerde JSON (`{squad, action, grid, voice_reply}`)
4. **Python → Game**: Python stuurt de JSON terug als HTTP response; Enforce Script voert het uit (waypoints, suppressie, etc.)
5. **Game → Operator**: Squadleden rapporteren via in-game sideChat/radio (fase 1: tekst, fase 2: TTS audio)

---

## 2. ENVIRONMENT INVENTORY

### 2.1 Game Installatie
| Eigenschap | Waarde |
|---|---|
| Game directory | `Q:\GAMES\Arma Reforger` |
| Executable | `ArmaReforger_BE.exe` |
| Addons | `addons/core/`, `addons/data/` |
| Main gproj | `addons/data/ArmaReforger.gproj` |
| Steam emulator | `tenoke.dll` / `tenoke.ini` (appid 1874880) |
| Workbench | **Niet geïnstalleerd** — niet nodig voor dit project |
| Workshop | **Niet beschikbaar** — mods worden lokaal geladen |

### 2.2 LLM Proxy
| Eigenschap | Waarde |
|---|---|
| URL | `http://192.168.1.35:11434/v1` |
| API Key | `goosedesktop_dc85e569751041ef9e1a2576fa2c2553` |
| Protocol | OpenAI-compatible (`/v1/chat/completions`) |
| JSON mode | ✅ Getest — `response_format: {type: "json_object"}` werkt |
| Function calling | ✅ Getest — `tools` + `tool_choice` werkt |
| Snel model | `llama3` (3B) — 335ms latency, function calling confirmed |
| Slim model | `qwen3.6-35b-fast` (35B MoE A3B) — ~2000ms, thinking model, heeft 800+ tokens nodig |
| Cloud fallbacks | GPT-5 series, Claude 3.5, Gemini, etc. via proxy |

### 2.3 Python
| Eigenschap | Waarde |
|---|---|
| Versie | Python 3.12.10 |
| Pad | `C:\Users\onyou\AppData\Local\Programs\Python\Python312\` |
| pip | 25.0.1 |
| venv | Beschikbaar |
| Whisper | **Niet geïnstalleerd** — wordt in fase 2 geïnstalleerd via `faster-whisper` |

### 2.4 Project Directory
| Pad | Inhoud |
|---|---|
| `Q:\GAMES\Reforger-LLM-Squad\` | Project root |
| `Q:\GAMES\Reforger-LLM-Squad\docs\` | Bohemia SampleMods referentie (Enforce Script voorbeelden) |
| `Q:\GAMES\Reforger-LLM-Squad\reforger_mod\` | Mod broncode (alle bestanden momenteel 0 bytes) |
| `Q:\GAMES\Reforger-LLM-Squad\python_bridge\` | Python backend (alle bestanden momenteel 0 bytes) |

### 2.5 Netwerk Referentie
| Eigenschap | Waarde |
|---|---|
| Game machine | Windows (localhost) |
| LLM proxy machine | `192.168.1.35` (LAN, zelfde netwerk) |
| Python bridge | localhost (`127.0.0.1:5000`) |
| Game → Python | HTTP POST via `RestContext` (Enfusion native) |
| Python → Proxy | HTTP via `openai` Python SDK |

---

## 3. CONSTRAINTS & ASSUMPTIONS

### 3.1 Hard Constraints
1. **Geen Workbench**: Enforce Script `.c` files worden als plain text geschreven. De game compileert scripts bij runtime.
2. **Geen Steam Workshop**: Mods worden lokaal geladen via `-mod` launch parameter.
3. **Geen BattlEye server**: Single-player of local hosted. Anti-cheat is niet actief in single-player.
4. **Enforce Script is geen C#**: Het lijkt erop, maar heeft beperkingen. Classes moeten in specifieke mappen, `modded class` syntax voor overrides.

### 3.2 Assumptions
1. De operator kan de game starten met custom launch parameters (`-mod`).
2. De game compileert unpacked `.c` bestanden bij opstarten (standaard Reforger gedrag).
3. De proxy blijft beschikbaar tijdens de volledige sessie.
4. Single-player scenario's werken zonder server-infrastructuur.

---

## 4. PHASED DELIVERY PLAN

### FASE 1: REST Bridge + AI Squad Control (Geen Voice)
**Doel**: Een werkende HTTP bridge tussen Reforger en de LLM proxy, waarbij de game squad telemetry verstuurt en gestructureerde commando's terugkrijgt.

#### F1.1 — Python Bridge (`python_bridge/main.py`)
- [ ] FastAPI server op `127.0.0.1:5000`
- [ ] `/health` endpoint (GET) — door Reforger gepingd bij mod startup
- [ ] `/sitrep` endpoint (POST) — ontvangt squad telemetry JSON van Reforger
- [ ] `/command` endpoint (POST) — ontvangt operator tekst commando, stuurt naar LLM, retourneert JSON
- [ ] OpenAI SDK koppeling naar proxy (`192.168.1.35:11434/v1`)
- [ ] Function calling schema: `issue_order(squad, action, grid, voice_reply)`
- [ ] JSON validatie op alle in/uitgaande payloads
- [ ] Timeout handling (3s) met fallback commando (HOLD)
- [ ] Gestructureerde logging naar `python_bridge/bridge.log`
- [ ] Config file (`python_bridge/config.json`) voor alle instellingen

#### F1.2 — Enforce Script (`reforger_mod/Scripts/Game/LLMBridge.c`)
- [ ] `LLMBridgeComponent` class (geïnstantieerd via modded game component)
- [ ] `RestContext` initialisatie naar `http://127.0.0.1:5000/`
- [ ] `RestCallback` subclass voor het afhandelen van responses
- [ ] `SendSitRep()` — verzamel squad telemetry en POST naar Python
- [ ] `ExecuteCommand()` — parse JSON response, maak AIWaypoint aan
- [ ] Health check bij startup — als Python niet draait, mod in "passive mode"
- [ ] Timer-based SITREP verzending (elke 10 seconden, configureerbaar)
- [ `sideChat` radio callbacks voor squad status reports
- [ ] Error handling — nooit crashen op REST failures

#### F1.3 — Mod Configuratie
- [ ] `reforger_mod/gproj.conf` — mod project metadata
- [ ] Mod directory structuur:
  ```
  reforger_mod/
    Scripts/
      Game/
        LLMBridge.c
    gproj.conf
  ```
- [ ] Launch parameter documentatie: `-mod Q:\GAMES\Reforger-LLM-Squad\reforger_mod`

#### F1.4 — Standalone Test Mode
- [ ] `python_bridge/test_client.py` — simuleert Reforger game state JSON
- [ ] Test zonder game draaiend: stuur fake SITREP → ontvang LLM commando
- [ ] Validatie dat function calling juiste JSON retourneert
- [ ] Latency meting (mic → LLM → commando)

#### F1.5 — Fase 1 Validatie
- [ ] Python server start zonder errors
- [ ] `/health` retourneert 200 OK
- [ ] Gesimuleerde SITREP → LLM → correcte JSON commando
- [ ] JSON schema validatie werkt (foute input → graceful fallback)
- [ ] Timeout fallback werkt (LLM > 3s → HOLD commando)

---

### FASE 2: Voice Pipeline (Spraak → Squad)
**Doel**: Operator spreekt in microfoon, Whisper zet om naar tekst, LLM vertaalt naar commando.

#### F2.1 — Whisper STT Integration
- [ ] `faster-whisper` installeren in Python venv
- [ ] Microfoon opname via `sounddevice`
- [ ] Push-to-Talk key listener (configbare toets, default `F24`)
- [ ] Audio → tekst conversie met latency logging
- [ ] `/voice` endpoint in FastAPI

#### F2.2 — Voice → LLM → Game Pipeline
- [ ] Audio opname → Whisper transcriptie
- [ ] Transcriptie → `/command` endpoint (hergebruik fase 1 logica)
- [ ] LLM → JSON commando → Reforger
- [ ] End-to-end latency meting en logging

#### F2.3 — Fase 2 Validatie
- [ ] PTT key werkt (start/stop opname)
- [ ] Whisper transcribeert correct
- [ ] Volledige pijplijn: spraak → tekst → LLM → JSON → game actie

---

### FASE 3: TTS Squad Terugkoppeling (Optioneel)
**Doel**: Squadleden "spreken" hun observaties hardop via TTS.

- [ ] Onderzoek TTS engine (Piper, XTTS, of Coqui)
- [ ] Integreer TTS in Python bridge
- [ ] `voice_reply` field uit LLM JSON → audio playback
- [ ] Radio-style audio in game (via `say3D` of extern audio kanaal)

---

## 5. GUARDRAILS

Deze guardrails zorgen ervoor dat het systeem faalt-safe is en de operator geen handmatige tussenkomst nodig heeft bij errors.

### 5.1 JSON Validatie
- **Python**: Alle inkomende JSON van Reforger wordt gevalideerd met Pydantic models. Ongeldige JSON = HTTP 422 + fallback response `{action: "HOLD", voice_reply: "Invalid data received"}`
- **Python**: Alle uitgaande JSON naar Reforger wordt gevalideerd tegen het function calling schema. Ongeldige LLM output = retry met striktere prompt of fallback HOLD
- **Enforce Script**: Alle inkomende JSON van Python wordt geparsed met try/catch. Parse failure = log + ignore (geen crash)

### 5.2 Timeout Handling
- **LLM call timeout**: 3 seconden. Bij timeout → fallback commando `{action: "HOLD", voice_reply: "Command timeout, holding position"}`
- **REST call timeout (Enforce Script)**: 5 seconden. Bij timeout → log + passive mode voor 10 seconden, dan retry
- **Health check retry**: 3 pogingen met 2s interval bij startup. Daarna passive mode

### 5.3 Rate Limiting
- **SITREP frequency**: Maximaal 1 per 10 seconden (configureerbaar in `config.json`)
- **LLM call frequency**: Maximaal 1 per 2 seconden om spam/loops te voorkomen
- **Queue**: Als een LLM call al loopt, nieuwe requests worden gequeued (max queue: 3, daarna drop oudste)

### 5.4 Error Handling
- **Python**: Alle exceptions worden gelogd naar `bridge.log` met timestamp. Server crasht nooit — FastAPI error handlers vangen alles
- **Enforce Script**: Alle `RestCallback` errors worden gelogd via `Print()`. Geen `throw`. Script_component blijft draaien in passive mode
- **Proxy unavailable**: Python detecteert dit, retourneert fallback naar game, logt error

### 5.5 Passive Mode
- Als Python server niet draait bij game startup → mod laadt in passive mode (geen LLM calls, squad gedraagt zich als standaard AI)
- Als proxy niet bereikbaar is → Python retourneert HOLD commando's, logt errors, probeert elke 30s opnieuw te verbinden
- Operator hoeft spel niet te herstarten als Python/proxy weer online komt — volgende SITREP cycle detecteert dit automatisch

### 5.6 Configuratie
Alle instellingen in één `python_bridge/config.json`:
```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 5000
  },
  "llm": {
    "base_url": "http://192.168.1.35:11434/v1",
    "api_key": "goosedesktop_dc85e569751041ef9e1a2576fa2c2553",
    "model": "llama3",
    "timeout_seconds": 3,
    "max_tokens": 300
  },
  "game": {
    "sitrep_interval_seconds": 10,
    "squad_names": ["ALPHA", "BRAVO", "CHARLIE"],
    "fallback_action": "HOLD"
  },
  "voice": {
    "enabled": false,
    "ptt_key": "F24",
    "whisper_model": "small",
    "whisper_device": "cpu",
    "whisper_compute_type": "int8"
  },
  "logging": {
    "level": "INFO",
    "file": "bridge.log"
  }
}
```

### 5.7 Operator Guardrails
Dingen die de operator **NIET zelf hoeft te doen** — de agent regelt dit:

| Taak | Wie | Hoe |
|---|---|---|
| Python venv aanmaken | Agent | `python -m venv` in project dir |
| Dependencies installeren | Agent | `pip install -r requirements.txt` |
| Config file genereren | Agent | Schrijft `config.json` met juiste proxy URL + key |
| Mod directory structuur | Agent | Maakt alle mappen + `.c` files |
| gproj.conf schrijven | Agent | Correcte mod metadata |
| Test scripts schrijven | Agent | `test_client.py` voor standalone testen |
| Launch parameter docs | Agent | Documentatie in README |
| Error logs lezen | Agent | Goose kan `bridge.log` inlezen bij problemen |

Dingen die de operator **WEL zelf moet doen**:

| Taak | Waarom |
|---|---|
| Game starten met `-mod` parameter | Game draait niet in goose's procesruimte |
| Microfoon toets indrukken (PTT) | Fysieke hardware interactie |
| In-game scenario laden | Game UI interactie |
| Proxy/llama-server draaiend houden | Externe machine (`192.168.1.35`) |

---

## 6. DELIVERABLES PER FASE

### Fase 1 Deliverables
| # | Bestand | Beschrijving |
|---|---|---|
| 1 | `python_bridge/main.py` | FastAPI server met /health, /sitrep, /command endpoints |
| 2 | `python_bridge/config.json` | Centrale configuratie |
| 3 | `python_bridge/requirements.txt` | Python dependencies |
| 4 | `python_bridge/test_client.py` | Standalone test script (zonder game) |
| 5 | `reforger_mod/Scripts/Game/LLMBridge.c` | Enforce Script REST bridge + AI control |
| 6 | `reforger_mod/gproj.conf` | Mod project config |
| 7 | `README.md` | Installatie & gebruik instructies |

### Fase 2 Deliverables
| # | Bestand | Beschrijving |
|---|---|---|
| 8 | `python_bridge/voice_handler.py` | Whisper STT + PTT listener |
| 9 | Update `python_bridge/main.py` | Voeg `/voice` endpoint toe |
| 10 | Update `python_bridge/config.json` | Voice settings geactiveerd |
| 11 | Update `python_bridge/requirements.txt` | faster-whisper, sounddevice deps |

---

## 7. TECHNICAL DECISIONS

### 7.1 Model Keuze
- **Fase 1**: `llama3` (3B) — 335ms latency, function calling bevestigd. Snel genoeg voor real-time squad control.
- **Fase 2**: Mogelijk upgrade naar `qwen3.6-35b-fast` voor complexere spraakinterpretatie, met `llama3` als fallback voor snelheid.
- **Configurabel**: Model staat in `config.json`, operator kan wijzigen zonder code aan te passen.

### 7.2 Function Calling vs JSON Mode
- **Voorkeur**: Function calling (`tools` + `tool_choice`) — gegarandeerde structured output, geen parsing nodig.
- **Fallback**: Als function calling faalt bij een specifiek model,切换 naar `response_format: json_object` met strikte system prompt.
- **Getest**: `llama3` met function calling werkt en retourneert correcte `tool_calls` in 335ms.

### 7.3 Mod Loading Mechanisme
- Zonder Workbench/Steam wordt de mod geladen als **unpacked addon directory**.
- Reforger ondersteunt `-mod <path>` parameter voor lokale mods.
- De game compileert `.c` bestanden bij runtime vanuit de mod directory.
- Structuur: mod directory moet `Scripts/Game/` bevatten met de `.c` bestanden, plus een `gproj.conf` of addon metadata.

### 7.4 Enforce Script Constraints (geleerd uit SampleMods)
- Classes gebruiken `modded class` syntax voor het uitbreiden van bestaande game classes.
- Components erven van `SCR_BaseGameModeComponent` of `ScriptComponent`.
- `RestContext` en `RestCallback` zijn native Enfusion classes voor HTTP.
- `AIWaypoint` wordt gespawnd via `GetGame().SpawnEntityPrefab()`.
- `SCR_AIGroup` is de container voor AI squad units.
- `Print()` voor logging (verschijnt in game `.log` bestand).
- Geen `throw` — Enforce Script heeft geen exception handling. Alles via return codes en null checks.

---

## 8. RISKS & MITIGATIONS

| Risico | Impact | Mitigatie |
|---|---|---|
| Enforce Script API niet volledig gedocumenteerd | Code compileert niet in game | Failsafe: mod laadt in passive mode als script errors bevat. Logs worden door Goose gelezen voor debugging. |
| Mod loading werkt niet zonder Workbench | Mod wordt niet geladen door game | Alternatief: handmatig `.pak` packing工具 onderzoeken, of scripts direct in game `addons/` directory plaatsen. |
| LLM hallucineert ongeldig grid/actie | Squad doet ongewenste acties | JSON schema enforcement via function calling. Python valideert action/grid enums. Onbekende grid = HOLD fallback. |
| Proxy machine uitvalt | Geen LLM responses | Passive mode, HOLD fallback, auto-retry elke 30s |
| Latency te hoog voor real-time control | Squad reageert traag | `llama3` (3B) als primair model — 335ms getest. SITREP interval configureerbaar. |
| Game update breekt mod API | Script compileert niet | Mod gebruikt `modded class` overrides die redelijk robuust zijn tegen minor updates. Logs geven compile errors. |

---

## 9. EXECUTION TIMELINE

### Dit Weekend (Fase 1 volledig)
1. **Agent schrijft alle Fase 1 deliverables** (main.py, config.json, requirements.txt, test_client.py, LLMBridge.c, gproj.conf, README.md)
2. **Agent creëert Python venv** en installeert dependencies
3. **Agent runt standalone test** (test_client.py) om LLM pipeline te valideren
4. **Operator start game** met `-mod` parameter
5. **Operator & agent valideren** in-game dat SITREP bridge werkt

### Volgende Week (Fase 2)
1. Agent installeert `faster-whisper` + `sounddevice`
2. Agent schrijft `voice_handler.py`
3. Operator test voice pipeline

### Daarna (Fase 3, optioneel)
1. TTS engine selectie en integratie
2. Audio playback in game

---

## 10. APPROVAL

**Operator**: Lees dit plan door. Als je akkoord gaat, zeg "go" en ik bouw Fase 1 volledig uit — alle bestanden, venv, dependencies, en standalone test.

Als je wijzigingen wilt, markeer ze en ik pas het plan aan voordat ik bouw.
