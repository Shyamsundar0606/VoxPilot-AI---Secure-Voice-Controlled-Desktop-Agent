from __future__ import annotations

import logging
import re
from threading import Event
from time import perf_counter

from app.models import WakeWordResult
from app.config import WAKE_PHRASE

logger = logging.getLogger(__name__)


def normalize_wake_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def is_wake_phrase(text: str) -> bool:
    return normalize_wake_text(text) == normalize_wake_text(WAKE_PHRASE)


class WakeWordController:
    """Energy-gated, local Whisper fallback over bounded audio windows."""

    def __init__(self, recorder, transcriber):
        self.recorder, self.transcriber = recorder, transcriber

    def listen_once(self, device: int | None, cancel_event: Event, level_callback=None, state_callback=None) -> WakeWordResult:
        started = perf_counter()
        if cancel_event.is_set(): return WakeWordResult(cancelled=True, message="Wake-word listening cancelled.")
        recording = self.recorder.record(device, cancel_event, level_callback)
        if cancel_event.is_set():
            self._clear(recording); return WakeWordResult(cancelled=True, message="Wake-word listening cancelled.")
        if not recording.success:
            self._clear(recording)
            if recording.error_code == "no_speech": return WakeWordResult(message="No wake speech detected.", processing_time=perf_counter() - started)
            return WakeWordResult(error_code=recording.error_code, message=recording.message, processing_time=perf_counter() - started)
        if state_callback: state_callback("Processing")
        try:
            transcript = self.transcriber.transcribe(recording, cancel_event)
        finally:
            self._clear(recording)
        if cancel_event.is_set():
            return WakeWordResult(cancelled=True, message="Wake-word listening cancelled.")
        if transcript.cancelled: return WakeWordResult(cancelled=True, message="Wake-word listening cancelled.")
        if not transcript.success:
            if transcript.error_code in {"empty_transcription", "low_confidence", "no_audio", "audio_too_short"}:
                return WakeWordResult(message="Speech did not contain a reliable wake phrase.", processing_time=perf_counter() - started)
            return WakeWordResult(error_code=transcript.error_code, message=transcript.message, processing_time=perf_counter() - started)
        detected = is_wake_phrase(transcript.text)
        logger.info("Wake-word window processed: detected=%s processing_time=%.3fs", detected, perf_counter() - started)
        return WakeWordResult(detected=detected, message="Wake phrase detected." if detected else "Speech did not contain the wake phrase.", processing_time=perf_counter() - started)

    @staticmethod
    def _clear(recording):
        audio = getattr(recording, "audio", None)
        if audio is not None: audio.fill(0); recording.audio = None
