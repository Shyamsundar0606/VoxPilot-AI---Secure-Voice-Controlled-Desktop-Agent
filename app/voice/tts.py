from __future__ import annotations

import logging
from queue import Queue
from threading import Thread

logger = logging.getLogger(__name__)


class TextToSpeech:
    def __init__(self, enabled: bool = True, engine_factory=None, timeout: float = 8.0):
        self.enabled = enabled
        self.engine_factory = engine_factory or self._default_engine
        self.last_error: str | None = None
        self.timeout = timeout
        self._queue: Queue[str] = Queue()
        self._worker = Thread(target=self._run_queue, name="voxpilot-tts", daemon=True)
        self._worker.start()

    @staticmethod
    def _default_engine():
        import pyttsx3
        return pyttsx3.init()

    def speak(self, text: str) -> bool:
        if not self.enabled:
            return False
        self._queue.put(text)
        return True

    def _run_queue(self) -> None:
        while True:
            text = self._queue.get()
            try:
                speech = Thread(target=self._speak_safely, args=(text,), name="voxpilot-tts-call", daemon=True)
                speech.start()
                speech.join(self.timeout)
                if speech.is_alive():
                    self.last_error = "TimeoutError"
                    logger.error("Text-to-speech timed out after %.1f seconds", self.timeout)
            finally:
                self._queue.task_done()

    def _speak_safely(self, text: str) -> None:
        try:
            engine = self.engine_factory()
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            self.last_error = type(exc).__name__
            logger.exception("Text-to-speech failed")
