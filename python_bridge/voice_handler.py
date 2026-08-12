"""
voice_handler.py — Phase 2: Voice Pipeline (Speech → Squad)

Push-to-Talk key listener + microphone capture + Whisper STT transcription.
On PTT release: captures audio → transcribes → calls bridge call_llm() → queues result in pending_orders.

Usage:
    from voice_handler import VoiceHandler
    vh = VoiceHandler(config, on_transcription_callback)
    vh.start()  # starts keyboard hook in background thread
    vh.stop()   # stops hook, joins thread
"""

import json
import time
import logging
import threading
import numpy as np
import sounddevice as sd

logger = logging.getLogger("reforger_voice")

# Lazy imports — these are heavy and only needed when voice is enabled
_keyboard = None
_WhisperModel = None

def _lazy_imports():
    global _keyboard, _WhisperModel
    if _keyboard is None:
        import keyboard
        _keyboard = keyboard
    if _WhisperModel is None:
        from faster_whisper import WhisperModel
        _WhisperModel = WhisperModel


class VoiceHandler:
    """Handles PTT key listening, audio capture, and Whisper transcription."""

    def __init__(self, voice_config: dict, on_transcription=None):
        self.enabled = voice_config.get("enabled", False)
        self.ptt_key = voice_config.get("ptt_key", "F24")
        self.whisper_model = voice_config.get("whisper_model", "small")
        self.whisper_device = voice_config.get("whisper_device", "cpu")
        self.whisper_compute_type = voice_config.get("whisper_compute_type", "int8")

        self._on_transcription = on_transcription  # callback(text: str)
        self._model = None
        self._thread = None
        self._running = False
        self._recording = False
        self._audio_chunks = []
        self._samplerate = 16000  # Whisper expects 16kHz
        self._stream = None
        self._last_transcription = ""
        self._last_transcription_time = 0

    def start(self):
        """Start the keyboard hook listener in a background thread."""
        if not self.enabled:
            logger.info("Voice handler disabled in config")
            return False

        try:
            _lazy_imports()
        except ImportError as e:
            logger.error(f"Voice dependencies not installed: {e}")
            return False

        # Load Whisper model (lazy, on first start)
        if self._model is None:
            logger.info(f"Loading Whisper model '{self.whisper_model}' (device={self.whisper_device}, compute={self.whisper_compute_type})...")
            t0 = time.time()
            self._model = _WhisperModel(
                self.whisper_model,
                device=self.whisper_device,
                compute_type=self.whisper_compute_type
            )
            logger.info(f"Whisper model loaded in {time.time()-t0:.1f}s")

        self._running = True
        self._thread = threading.Thread(target=self._hook_loop, daemon=True)
        self._thread.start()
        logger.info(f"Voice handler started — PTT key: {self.ptt_key}")
        return True

    def stop(self):
        """Stop the keyboard hook and join thread."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        logger.info("Voice handler stopped")

    def _hook_loop(self):
        """Background thread that listens for PTT key press/release."""
        try:
            # Register hotkey callbacks
            _keyboard.on_press_key(self.ptt_key, self._on_ptt_press)
            _keyboard.on_release_key(self.ptt_key, self._on_ptt_release)

            # Keep thread alive
            while self._running:
                time.sleep(0.1)

            # Unhook everything
            _keyboard.unhook_all()
        except Exception as e:
            logger.error(f"Voice hook loop error: {e}")

    def _on_ptt_press(self, event):
        """PTT key pressed — start recording."""
        if self._recording:
            return
        self._recording = True
        self._audio_chunks = []
        logger.info(f"[PTT] Recording started (key={event.name})")

        try:
            self._stream = sd.InputStream(
                samplerate=self._samplerate,
                channels=1,
                dtype='float32',
                callback=self._audio_callback
            )
            self._stream.start()
        except Exception as e:
            logger.error(f"[PTT] Failed to start audio stream: {e}")
            self._recording = False

    def _audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice when audio data is available."""
        if self._recording:
            self._audio_chunks.append(indata.copy())

    def _on_ptt_release(self, event):
        """PTT key released — stop recording, transcribe, call callback."""
        if not self._recording:
            return
        self._recording = False
        logger.info("[PTT] Recording stopped, transcribing...")

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._audio_chunks:
            logger.warning("[PTT] No audio captured")
            return

        # BUGFIX: copy chunks BEFORE releasing _recording state — a fast re-press
        # resets self._audio_chunks in _on_ptt_press, and np.concatenate would
        # crash with "need at least one array" killing the keyboard hook thread.
        chunks = list(self._audio_chunks)

        # Concatenate audio chunks
        try:
            audio = np.concatenate(chunks, axis=0).flatten()
        except Exception as e:
            logger.error(f"[PTT] Audio concat failed: {e}")
            return
        duration = len(audio) / self._samplerate
        logger.info(f"[PTT] Captured {duration:.1f}s of audio ({len(audio)} samples)")

        if duration < 0.3:
            logger.warning("[PTT] Audio too short (<0.3s), ignoring")
            return

        # Transcribe with Whisper
        t0 = time.time()
        try:
            segments, info = self._model.transcribe(
                audio,
                language="en",
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300)
            )
            # faster-whisper returns a generator — consume it
            text = " ".join([s.text.strip() for s in segments]).strip()
            latency = time.time() - t0
            logger.info(f"[PTT] Transcribed in {latency:.1f}s: \"{text}\"")

            self._last_transcription = text
            self._last_transcription_time = time.time()

            if text and self._on_transcription:
                # BUGFIX: run the callback (LLM call, ~2-5s blocking) in a separate
                # thread — otherwise the keyboard hook thread is blocked and PTT
                # presses during transcription are lost.
                threading.Thread(target=self._on_transcription, args=(text,), daemon=True).start()

        except Exception as e:
            logger.error(f"[PTT] Whisper transcription failed: {e}")

    def get_status(self) -> dict:
        """Return current voice handler status."""
        return {
            "enabled": self.enabled,
            "ptt_key": self.ptt_key,
            "model": self.whisper_model,
            "recording": self._recording,
            "last_transcription": self._last_transcription,
            "last_transcription_age": round(time.time() - self._last_transcription_time, 1) if self._last_transcription_time > 0 else None,
            "model_loaded": self._model is not None,
            "running": self._running,
        }

    def transcribe_file(self, file_path: str) -> str:
        """Transcribe an audio file directly (for testing)."""
        if self._model is None:
            _lazy_imports()
            self._model = _WhisperModel(
                self.whisper_model,
                device=self.whisper_device,
                compute_type=self.whisper_compute_type
            )
        segments, info = self._model.transcribe(file_path, language="en", beam_size=1)
        return " ".join([s.text.strip() for s in segments]).strip()
