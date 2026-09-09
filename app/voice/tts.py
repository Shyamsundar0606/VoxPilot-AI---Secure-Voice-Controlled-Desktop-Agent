from __future__ import annotations

import logging
from queue import Queue
from threading import Event, Thread, Lock
from multiprocessing import get_context

logger = logging.getLogger(__name__)


def _native_speech(text, connection):
    """Isolate the Windows speech engine so a hung driver can be stopped."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        engine.stop()
        connection.send(None)
    except Exception as exc:
        connection.send(type(exc).__name__)
    finally:
        connection.close()


class TextToSpeech:
    def __init__(self, enabled: bool = True, engine_factory=None, timeout: float = 8.0):
        self.enabled = enabled
        self.engine_factory = engine_factory or self._default_engine
        self._native = engine_factory is None
        self._closed = Event()
        self._state_lock = Lock()
        self._process = None
        self.last_error: str | None = None
        self.timeout = timeout
        self._queue: Queue[str] = Queue()
        self._busy = Event()
        self._worker = Thread(target=self._run_queue, name="voxpilot-tts", daemon=True)
        self._worker.start()

    @staticmethod
    def _default_engine():
        import pyttsx3
        return pyttsx3.init()

    def speak(self, text: str) -> bool:
        with self._state_lock:
            if not self.enabled or self._closed.is_set():
                return False
            self._busy.set()
            self._queue.put(text)
        return True

    def _run_queue(self) -> None:
        while True:
            text = self._queue.get()
            try:
                if text is None: return
                if self._closed.is_set(): continue
                if self._native:
                    self._speak_process(text)
                    continue
                speech = Thread(target=self._speak_safely, args=(text,), name="voxpilot-tts-call", daemon=True)
                speech.start()
                speech.join(self.timeout)
                if speech.is_alive():
                    self.last_error = "TimeoutError"
                    logger.error("Text-to-speech timed out after %.1f seconds", self.timeout)
            finally:
                with self._state_lock:
                    if self._queue.empty(): self._busy.clear()
                self._queue.task_done()

    def _speak_process(self, text):
        context = get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_native_speech, args=(text, sender), daemon=True)
        try:
            process.start()
            self._process = process
            sender.close()
            process.join(self.timeout)
            if process.is_alive():
                self.last_error = "TimeoutError"
                process.terminate()
                process.join()
            elif receiver.poll():
                self.last_error = receiver.recv()
        except Exception as exc:
            self.last_error = type(exc).__name__
        finally:
            if process.is_alive():
                process.terminate(); process.join()
            self._process = None
            receiver.close(); sender.close()

    def shutdown(self):
        with self._state_lock:
            if self._closed.is_set(): return
            self._closed.set()
            self._queue.put(None)
        process = self._process
        if process is not None and process.is_alive(): process.terminate()
        self._worker.join(self.timeout + 1)
        self._busy.clear()

    def is_busy(self) -> bool:
        return self._busy.is_set()

    def _speak_safely(self, text: str) -> None:
        try:
            engine = self.engine_factory()
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            self.last_error = type(exc).__name__
            logger.exception("Text-to-speech failed")
