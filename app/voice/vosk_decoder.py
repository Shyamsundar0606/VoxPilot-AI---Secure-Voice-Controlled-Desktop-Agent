"""Persistent local Vosk model, isolated from the GUI and microphone owner."""
import json
from multiprocessing import get_context
from pathlib import Path
from threading import Event
from time import monotonic

from app.config import PROJECT_ROOT

MESSAGES = {
    "missing_model": "Vosk wake model is missing. Download and extract vosk-model-small-en-us-0.15 from alphacephei.com/vosk/models, set VOSK_MODEL_PATH to its local folder, then re-enable wake mode. No model is downloaded automatically.",
    "vosk_unavailable": "Vosk is unavailable. Install vosk==0.3.45 in your Python 3.12 environment, then re-enable wake mode.",
    "invalid_model": "The local Vosk model could not be loaded. Check VOSK_MODEL_PATH and use a small model supporting constrained grammar.",
    "decoder_failed": "Local Vosk wake detection stopped. Re-enable wake mode to retry.",
    "decoder_timeout": "Local Vosk wake detection timed out. Re-enable wake mode to retry.",
    "cancelled": "Wake-word listening cancelled.",
}


class WakeDecoderError(ValueError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else "decoder_failed"
        super().__init__(MESSAGES[self.code])


def _vosk_process(connection, path):
    """Explicit path only: never Model(lang=...) or automatic downloads."""
    recognizer = model = None
    try:
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
        except (ImportError, OSError):
            connection.send((False, "vosk_unavailable")); return
        SetLogLevel(-1)
        try: model = Model(model_path=path)
        except Exception:
            connection.send((False, "invalid_model")); return
        connection.send((True, None))
        while True:
            command, payload = connection.recv()
            try:
                if command == "start":
                    recognizer = KaldiRecognizer(model, 16000, json.dumps([payload, "[unk]"]))
                    connection.send((True, None))
                elif command == "frame" and recognizer is not None:
                    # PartialResult and FinalResult-on-close are never used.
                    final = json.loads(recognizer.Result()) if recognizer.AcceptWaveform(bytes(payload)) else {}
                    text = final.get("text", "")
                    connection.send((True, text if isinstance(text, str) and len(text) <= 500 else ""))
                elif command == "reset":
                    recognizer = None
                    connection.send((True, None))
                else: break
            except Exception:
                connection.send((False, "decoder_failed")); break
            finally:
                if isinstance(payload, bytearray): payload[:] = b"\x00" * len(payload)
                payload = None
    except (EOFError, OSError):
        pass
    finally:
        recognizer = model = None
        connection.close()


class VoskDecoder:
    def __init__(self, model_path, context_factory=get_context):
        self.model_path = Path(model_path)
        self.context_factory = context_factory
        self.process = self.connection = None

    def start(self, phrase, cancel):
        if cancel.is_set(): raise WakeDecoderError("cancelled")
        if self.process is None:
            path = self.model_path
            if not path.is_absolute(): path = PROJECT_ROOT / path
            if str(path).startswith(("\\\\", "//")) or not path.is_dir():
                raise WakeDecoderError("missing_model")
            context = self.context_factory("spawn")
            self.connection, child = context.Pipe()
            self.process = context.Process(target=_vosk_process, args=(child, str(path)), daemon=True)
            try:
                self.process.start(); child.close()
                self._receive(cancel, 30)
            except Exception:
                child.close(); self.shutdown(); raise
        self._request("start", phrase, cancel)

    def feed(self, pcm, cancel):
        return self._request("frame", pcm, cancel)

    def reset(self):
        if self.process is not None:
            try: self._request("reset", None, Event(), timeout=1)
            except WakeDecoderError: pass

    def _request(self, command, payload, cancel, timeout=5):
        try:
            if cancel.is_set(): raise WakeDecoderError("cancelled")
            self.connection.send((command, payload))
            return self._receive(cancel, timeout)
        except (OSError, EOFError, AttributeError):
            self.shutdown(); raise WakeDecoderError("decoder_failed") from None

    def _receive(self, cancel, timeout):
        started = monotonic()
        try:
            while True:
                if cancel.is_set(): raise WakeDecoderError("cancelled")
                if monotonic() - started >= timeout: raise WakeDecoderError("decoder_timeout")
                if self.connection.poll(.02):
                    success, value = self.connection.recv()
                    if not success: raise WakeDecoderError(value)
                    return value
                if not self.process.is_alive(): raise WakeDecoderError("decoder_failed")
        except (WakeDecoderError, OSError, EOFError):
            self.shutdown(); raise

    def shutdown(self):
        process, self.process = self.process, None
        connection, self.connection = self.connection, None
        if process is not None and process.pid is not None:
            if process.is_alive(): process.terminate()
            process.join(); process.close()
        if connection is not None: connection.close()
