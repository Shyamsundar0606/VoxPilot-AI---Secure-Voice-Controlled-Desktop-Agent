from __future__ import annotations

import logging
from pathlib import Path
from threading import Event, Lock, Thread
from time import perf_counter
from multiprocessing import get_context
from types import SimpleNamespace

from app.models import RecordingResult, TranscriptionResult

logger = logging.getLogger(__name__)


def _whisper_process(connection, model_name, device, compute_type, local_only):
    """Keep one native model in a stoppable local process."""
    model = None
    try:
        while True:
            audio, options = connection.recv()
            try:
                if model is None:
                    from faster_whisper import WhisperModel
                    model = WhisperModel(model_name, device=device, compute_type=compute_type, local_files_only=local_only)
                segments, info = model.transcribe(audio, **options)
                texts = [segment.text for segment in segments]
                connection.send((texts, info.language, info.language_probability))
            except Exception:
                connection.send(None)
            finally:
                audio.fill(0)
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


class _WhisperProcessModel:
    def __init__(self, settings, local_only):
        context = get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=_whisper_process,
            args=(child, settings.whisper_model_size, settings.whisper_device,
                  settings.whisper_compute_type, local_only),
            daemon=True,
        )
        self.process.start()
        child.close()

    def transcribe(self, audio, **options):
        self.connection.send((audio, options))
        response = self.connection.recv()
        if response is None: raise RuntimeError("Local model unavailable")
        texts, language, probability = response
        return [SimpleNamespace(text=text) for text in texts], SimpleNamespace(language=language, language_probability=probability)

    def shutdown(self):
        if self.process.is_alive(): self.process.terminate()
        self.process.join()
        self.connection.close()


class SpeechTranscriber:
    def __init__(self, settings, model_factory=None, allow_download: bool = False):
        self.settings = settings
        self.model_factory = model_factory or self._default_factory
        self.allow_download = allow_download
        self._model = None
        self._model_lock = Lock()
        self._inference_lock = Lock()

    def model_cached(self) -> bool:
        model = Path(self.settings.whisper_model_size)
        if model.exists():
            return True
        cache_root = Path.home() / ".cache" / "huggingface" / "hub"
        name = "models--Systran--faster-whisper-" + self.settings.whisper_model_size.replace("/", "--")
        return (cache_root / name).exists()

    def transcribe(self, recording: RecordingResult, cancel_event: Event | None = None) -> TranscriptionResult:
        started = perf_counter(); cancel_event = cancel_event or Event()
        if cancel_event.is_set():
            self._clear_recording(recording)
            return self._failure("cancelled", "Transcription was cancelled.", started, cancelled=True)
        if not recording.success or recording.audio is None:
            self._clear_recording(recording)
            return self._failure("no_audio", "No valid speech audio is available.", started)
        if recording.speech_duration < self.settings.min_speech_seconds:
            self._clear_recording(recording)
            return self._failure("audio_too_short", "The spoken command was too short.", started)
        if not self._inference_lock.acquire(blocking=False):
            self._clear_recording(recording)
            return self._failure("busy", "The previous local transcription is still finishing.", started)
        try:
            holder: dict[str, object] = {}
            error: list[Exception] = []
            inference_audio = recording.audio.copy()
            recording.audio.fill(0)
            recording.audio = None

            def invoke():
                try:
                    if cancel_event.is_set(): return
                    model = self._load_model()
                    segments, info = model.transcribe(inference_audio, language=self.settings.whisper_language, beam_size=self.settings.whisper_beam_size, vad_filter=True)
                    holder["value"] = (list(segments), info)
                except Exception as exc:
                    error.append(exc)
                finally:
                    inference_audio.fill(0)
                    self._inference_lock.release()

            task = Thread(target=invoke, name="voxpilot-whisper-call", daemon=True); task.start()
            while task.is_alive() and perf_counter() - started < self.settings.transcription_timeout:
                if cancel_event.is_set():
                    self._stop_native_model()
                    task.join(0.2)
                    return self._failure("cancelled", "Transcription was cancelled.", started, cancelled=True)
                task.join(0.01)
            if task.is_alive():
                self._stop_native_model()
                task.join(0.2)
                return self._failure("timeout", "Local transcription timed out.", started)
            if error:
                raise error[0]
            segments, info = holder["value"]
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
            probability = float(getattr(info, "language_probability", 1.0))
            language = str(getattr(info, "language", self.settings.whisper_language))
            if cancel_event.is_set():
                return self._failure("cancelled", "Transcription was cancelled.", started, cancelled=True)
            if not text:
                return self._failure("empty_transcription", "No recognizable command was found.", started)
            if probability < self.settings.min_language_probability:
                return self._failure("low_confidence", "The command was not clear enough. Please repeat or type it.", started)
            return TranscriptionResult(success=True, text=text, language=language, language_probability=probability, duration=recording.duration, processing_time=perf_counter() - started, model_used=self.settings.whisper_model_size, message="Transcription completed.")
        except Exception:
            logger.exception("Local Whisper transcription failed")
            return self._failure("model_unavailable", "The local speech model could not be loaded or used.", started)
        finally:
            logger.info(
                "Whisper transcription: original_duration=%.3fs input_duration=%.3fs processing_time=%.3fs model=%s beam_size=%s",
                recording.original_duration, recording.duration, perf_counter() - started,
                self.settings.whisper_model_size, self.settings.whisper_beam_size,
            )
            if recording.audio is not None:
                recording.audio.fill(0)
                recording.audio = None

    def _load_model(self):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    if not self.allow_download and not self.model_cached():
                        raise FileNotFoundError("Whisper model is not cached")
                    self._model = self.model_factory()
                    logger.info(
                        "Shared Whisper model created: model=%s device=%s compute_type=%s beam_size=%s",
                        self.settings.whisper_model_size,
                        self.settings.whisper_device,
                        self.settings.whisper_compute_type,
                        self.settings.whisper_beam_size,
                    )
        return self._model

    def _default_factory(self):
        return _WhisperProcessModel(self.settings, local_only=not self.allow_download)

    def _stop_native_model(self):
        with self._model_lock:
            if isinstance(self._model, _WhisperProcessModel):
                self._model.shutdown()
                self._model = None

    def shutdown(self):
        self._stop_native_model()

    def _failure(self, code, message, started, cancelled=False):
        return TranscriptionResult(success=False, model_used=self.settings.whisper_model_size, processing_time=perf_counter() - started, cancelled=cancelled, error_code=code, message=message)

    @staticmethod
    def _clear_recording(recording: RecordingResult) -> None:
        if recording.audio is not None:
            recording.audio.fill(0)
            recording.audio = None
