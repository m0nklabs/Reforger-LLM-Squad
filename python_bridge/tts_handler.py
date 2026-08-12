"""
TTS Handler for Reforger LLM Squad Control.
Phase 3: Squad members "speak" their observations via TTS.

Primary: edge-tts (Microsoft Edge TTS, async, high quality, requires internet)
Fallback: pyttsx3 (offline, SAPI5, lower quality, no internet needed)

Each squad member gets a distinct voice for immersion.
"""
import asyncio
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger("tts_handler")

# Voice assignments for squad members (edge-tts voice IDs)
EDGE_VOICES = [
    "en-US-GuyNeural",      # Alpha - male, confident
    "en-US-DavisNeural",    # Bravo - male, deeper
    "en-US-JasonNeural",    # Charlie - male, younger
    "en-US-TonyNeural",     # Delta - male, mature
    "en-US-EricNeural",     # Echo - male, deep
    "en-US-RogerNeural",    # Foxtrot - male, gruff
    "en-US-BrianNeural",    # Golf - male, British
    "en-US-BrandonNeural",  # Hotel - male, neutral
    "en-US-ChristopherNeural",  # India - male, professional
    "en-US-AndrewNeural",   # Juliet - male, warm
]

# pyttsx3 voice indices (0=male, 1=female on Windows SAPI5)
PYTTSX3_VOICES = [0, 0, 1, 0, 0, 0, 0, 0, 0, 0]


# C.3: per-soldier voice overrides (name -> EDGE_VOICES index), persisted
# so the operator's choices survive bridge restarts. File is gitignored.
VOICE_ASSIGNMENTS_FILE = Path(__file__).resolve().parent / "voice_assignments.json"


def _load_voice_assignments() -> dict:
    """C.3: load {name: index} overrides from disk, validating indices."""
    try:
        with open(VOICE_ASSIGNMENTS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        return {
            str(k): int(v)
            for k, v in raw.items()
            if 0 <= int(v) < len(EDGE_VOICES)
        }
    except (json.JSONDecodeError, IOError, ValueError, TypeError):
        return {}


class TTSHandler:
    """Handles text-to-speech for squad member voice replies."""

    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.engine = config.get("engine", "auto")  # auto, edge, pyttsx3
        self.rate = config.get("rate", 150)  # words per minute (pyttsx3)
        self.volume = config.get("volume", 0.9)  # 0.0-1.0
        self._edge_available = False
        self._pyttsx3_engine = None
        self._pyttsx3_voices = []
        self._lock = threading.Lock()
        self._last_spoken = ""
        self._last_spoken_time = 0
        self._min_interval = 2.0  # min seconds between TTS calls
        self._running = False
        self._loop = None
        # C.3: per-soldier voice overrides (name -> EDGE_VOICES index)
        self.voice_overrides = _load_voice_assignments()
        if self.voice_overrides:
            logger.info(f"[C.3] voice overrides loaded: {self.voice_overrides}")

        # Check availability
        try:
            import edge_tts
            self._edge_available = True
            logger.info("edge-tts available (primary TTS engine)")
        except ImportError:
            logger.info("edge-tts not available, will use pyttsx3 fallback")

    def start(self):
        """Initialize TTS engines."""
        if not self.enabled:
            logger.info("TTS disabled in config")
            return

        # Start asyncio event loop for edge-tts
        self._loop = asyncio.new_event_loop()
        self._running = True

        # Init pyttsx3 as fallback
        if self.engine in ("auto", "pyttsx3"):
            try:
                import pyttsx3
                self._pyttsx3_engine = pyttsx3.init()
                self._pyttsx3_engine.setProperty("rate", self.rate)
                self._pyttsx3_engine.setProperty("volume", self.volume)
                self._pyttsx3_voices = self._pyttsx3_engine.getProperty("voices")
                logger.info(f"pyttsx3 initialized ({len(self._pyttsx3_voices)} voices available)")
            except Exception as e:
                logger.warning(f"pyttsx3 init failed: {e}")

        logger.info(f"TTS handler started (engine={self.engine}, edge={self._edge_available})")

    def stop(self):
        """Shutdown TTS."""
        self._running = False
        if self._loop:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except:
                pass

    def speak(self, text: str, member_index: int = 0, member_name: str = ""):
        """Speak text using TTS. Runs in background thread to avoid blocking."""
        if not self.enabled or not self._running or not text or not text.strip():
            return

        # Rate limit: don't speak too frequently
        now = __import__("time").time()
        if now - self._last_spoken_time < self._min_interval:
            logger.debug(f"TTS rate-limited, skipping: {text[:30]}...")
            return

        # Don't repeat the same text
        if text.strip().lower() == self._last_spoken.lower():
            return

        self._last_spoken = text.strip()
        self._last_spoken_time = now

        # Speak in background thread
        thread = threading.Thread(
            target=self._speak_sync,
            args=(text, member_index, member_name),
            daemon=True
        )
        thread.start()

    def _speak_sync(self, text: str, member_index: int, member_name: str):
        """Speak text synchronously (called from background thread)."""
        # Try edge-tts first (if available and selected)
        if self.engine in ("auto", "edge") and self._edge_available:
            if self._speak_edge(text, member_index):
                return

        # Fallback to pyttsx3
        if self._pyttsx3_engine:
            self._speak_pyttsx3(text, member_index)
            return

        logger.debug(f"No TTS engine available, skipping: {text[:30]}...")

    def assign_voice(self, name: str, voice) -> bool:
        """C.3: override a soldier's voice (index 0..N-1, or a voice id
        string, or None/-1 to remove the override). Persists to disk."""
        if not name:
            return False
        if voice is None or voice == -1 or voice == "default" or voice == "":
            self.voice_overrides.pop(name, None)
        else:
            try:
                idx = int(voice)
            except (ValueError, TypeError):
                # voice id string -> index
                idx = EDGE_VOICES.index(str(voice)) if str(voice) in EDGE_VOICES else -1
            if not (0 <= idx < len(EDGE_VOICES)):
                return False
            self.voice_overrides[name] = idx
        try:
            with open(VOICE_ASSIGNMENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.voice_overrides, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.warning(f"[C.3] voice assignments persist failed: {e}")
        logger.info(f"[C.3] voice assignment {name} -> {self.voice_overrides.get(name, 'default')}")
        return True

    def _resolve_voice_index(self, member_name: str, member_index: int) -> int:
        """C.3: per-soldier override wins over the fixed-by-index default."""
        if member_name and member_name in self.voice_overrides:
            return self.voice_overrides[member_name]
        return member_index

    def _speak_edge(self, text: str, member_index: int, member_name: str = "") -> bool:
        """Speak using edge-tts. Returns True on success."""
        try:
            import edge_tts
            import subprocess
            import platform

            voice = EDGE_VOICES[self._resolve_voice_index(member_name, member_index) % len(EDGE_VOICES)]

            # Generate audio file
            tmp_file = os.path.join(tempfile.gettempdir(), f"reforger_tts_{threading.get_ident()}.mp3")

            # BUGFIX: guard the shared asyncio loop with a lock — speak() spawns a
            # new thread per call and two overlapping calls would hit
            # "This event loop is already running" on the second run_until_complete.
            with self._lock:
                # Run edge-tts in the dedicated event loop
                async def _generate():
                    communicate = edge_tts.Communicate(text, voice)
                    await communicate.save(tmp_file)

                asyncio.set_event_loop(self._loop)
                self._loop.run_until_complete(_generate())

            if not os.path.exists(tmp_file):
                return False

            # Play audio using Windows media player (powershell)
            if platform.system() == "Windows":
                # Use powershell to play audio (built-in, no extra deps)
                ps_cmd = f'(New-Object Media.SoundPlayer "{tmp_file}").PlaySync()'
                # Actually, .mp3 needs different approach - use ffplay or Windows Media Player
                # Use startsound when available, or just use the simpler approach
                import subprocess
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Add-Type -AssemblyName presentationCore; "
                     f"$player = New-Object System.Windows.Media.MediaPlayer; "
                     f"$player.Open('{tmp_file}'); "
                     f"Start-Sleep -Milliseconds 200; "
                     f"$player.Play(); "
                     f"Start-Sleep -Seconds 3; "  # rough duration
                     f"$player.Close()"],
                    capture_output=True, timeout=10
                )

            logger.info(f"TTS[edge]: {text[:50]}...")
            return True

        except Exception as e:
            logger.warning(f"edge-tts failed: {e}")
            return False

    def _speak_pyttsx3(self, text: str, member_index: int, member_name: str = ""):
        """Speak using pyttsx3 (offline fallback)."""
        try:
            with self._lock:
                # Set voice if available
                if self._pyttsx3_voices and len(self._pyttsx3_voices) > 0:
                    voice_idx = PYTTSX3_VOICES[self._resolve_voice_index(member_name, member_index) % len(PYTTSX3_VOICES)]
                    if voice_idx < len(self._pyttsx3_voices):
                        self._pyttsx3_engine.setProperty(
                            "voice", self._pyttsx3_voices[voice_idx].id
                        )

                self._pyttsx3_engine.say(text)
                self._pyttsx3_engine.runAndWait()

            logger.info(f"TTS[pyttsx3]: {text[:50]}...")
        except Exception as e:
            logger.warning(f"pyttsx3 speak failed: {e}")

    def get_status(self) -> dict:
        """Return TTS status for /tts endpoint."""
        return {
            "enabled": self.enabled,
            "engine": self.engine,
            "edge_available": self._edge_available,
            "pyttsx3_available": self._pyttsx3_engine is not None,
            "running": self._running,
            "last_spoken": self._last_spoken[:80] if self._last_spoken else "",
            "voices": len(EDGE_VOICES),
            # C.3: voice picker data for the dashboard
            "voice_options": EDGE_VOICES,
            "assignments": {
                name: EDGE_VOICES[idx] for name, idx in sorted(self.voice_overrides.items())
            },
        }
