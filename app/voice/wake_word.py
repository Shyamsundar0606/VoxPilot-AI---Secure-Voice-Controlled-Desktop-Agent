"""Continuous local Vosk wake detection; no command transcription here."""
import re
from queue import Queue, Empty, Full
from threading import Event, Lock
from time import monotonic

import numpy as np

from app.config import configured_wake_phrase
from app.models import WakeWordResult
from app.voice.recorder import AudioRecorder
from app.voice.vosk_decoder import VoskDecoder, WakeDecoderError


def normalize_wake_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def is_wake_phrase(text: str, phrase=None) -> bool:
    expected = normalize_wake_text(phrase if phrase is not None else configured_wake_phrase())
    return bool(expected) and normalize_wake_text(text) == expected


class WakeWordController:
    FRAME_SECONDS = .05

    def __init__(self, settings, device_service, backend=None, decoder=None):
        self.phrase = settings.wake_phrase
        self.sensitivity = settings.microphone_sensitivity
        self.engine, self.sample_rate = settings.wake_engine, settings.vosk_sample_rate
        self.device_service = device_service
        if backend is None:
            import sounddevice as backend
        self.backend = backend
        self.decoder = decoder or VoskDecoder(settings.vosk_model_path)
        self._session_lock = Lock()

    def listen_once(self, device, cancel_event, level_callback=None, state_callback=None):
        if cancel_event.is_set(): return WakeWordResult(cancelled=True)
        if not self._session_lock.acquire(blocking=False):
            return WakeWordResult(error_code="microphone_busy", message="Wake listening is already active.")
        queue, interrupted = Queue(maxsize=20), Event()
        frame = pcm = None
        owned = False
        resample_state = None
        def callback(indata, frames, timing, status):
            if cancel_event.is_set(): return
            if status: interrupted.set(); return
            data = bytearray(indata)
            try: queue.put_nowait(data)
            except Full:
                data[:] = b"\x00" * len(data); interrupted.set()
        try:
            phrase = normalize_wake_text(self.phrase)
            if self.engine != "vosk" or self.sample_rate != 16000 or not re.fullmatch(r"[a-z]+(?: [a-z]+)*", phrase) or len(phrase) > 80 or phrase == "unk":
                return WakeWordResult(error_code="invalid_configuration", message="Wake detection requires VOXPILOT_WAKE_ENGINE=vosk, VOSK_SAMPLE_RATE=16000 and a non-empty wake phrase.")
            self.decoder.start(phrase, cancel_event)
            if not AudioRecorder._microphone_lock.acquire(blocking=False):
                return WakeWordResult(error_code="microphone_busy", message="The microphone is already in use.")
            owned = True
            resolved = self.device_service.resolve_for_recording(device)
            source_rate = resolved.sample_rate
            if not 8000 <= source_rate <= 192000: raise ValueError("Unsupported sample rate")
            blocksize = round(source_rate * self.FRAME_SECONDS)
            with self.backend.RawInputStream(device=resolved.identifier, samplerate=source_rate,
                    channels=1, dtype="int16", blocksize=blocksize, callback=callback):
                if state_callback: state_callback("Wake-word listening")
                last_frame = monotonic()
                while not cancel_event.is_set():
                    if interrupted.is_set(): raise OSError("Audio stream interrupted")
                    try: frame = queue.get(timeout=.05)
                    except Empty:
                        if monotonic() - last_frame > 2: raise OSError("No microphone frames")
                        continue
                    last_frame = monotonic()
                    try:
                        if source_rate != 16000:
                            import audioop  # Stateful PCM conversion; target runtime is Python 3.12.
                            converted, resample_state = audioop.ratecv(frame, 2, 1, source_rate, 16000, resample_state)
                            pcm = bytearray(converted); converted = None
                        else: pcm = bytearray(frame)
                        samples = np.frombuffer(pcm, dtype="<i2")
                        if self.sensitivity == "high":
                            amplified = np.clip(samples.astype(np.int32) * 2, -32768, 32767)
                            samples[:] = amplified; amplified.fill(0)
                        if level_callback and samples.size:
                            level_callback(float(np.max(np.abs(samples.astype(np.int32)))) / 32768)
                        # Silence is fed too: Vosk needs it to finalize an utterance.
                        text = self.decoder.feed(pcm, cancel_event)
                        if not cancel_event.is_set() and is_wake_phrase(text, self.phrase):
                            return WakeWordResult(detected=True, message="Wake phrase detected.")
                    finally:
                        if pcm is not None: pcm[:] = b"\x00" * len(pcm)
                        if frame is not None: frame[:] = b"\x00" * len(frame)
                        frame = pcm = None
            return WakeWordResult(cancelled=True, message="Wake-word listening cancelled.")
        except WakeDecoderError as exc:
            return WakeWordResult(cancelled=exc.code == "cancelled", error_code=None if exc.code == "cancelled" else exc.code, message=str(exc))
        except Exception:
            return WakeWordResult(cancelled=cancel_event.is_set(), error_code=None if cancel_event.is_set() else "invalid_device",
                message="Wake microphone disconnected or unavailable. Reconnect it or select another microphone; wake listening will retry.")
        finally:
            # RawInputStream has closed before the lock or activation is released.
            while True:
                try:
                    pending = queue.get_nowait(); pending[:] = b"\x00" * len(pending)
                except Empty: break
            resample_state = None
            try: self.decoder.reset()
            finally:
                if owned: AudioRecorder._microphone_lock.release()
                self._session_lock.release()

    def shutdown(self):
        self.decoder.shutdown()
