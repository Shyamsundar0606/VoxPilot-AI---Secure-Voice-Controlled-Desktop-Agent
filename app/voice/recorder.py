from __future__ import annotations

import logging
import wave
from queue import Empty, Queue
from threading import Event
from time import monotonic

import numpy as np

from app.models import RecordingResult, ResolvedAudioDevice
from app.voice.audio_devices import AudioDeviceService, DeviceResolutionError

logger = logging.getLogger(__name__)


class AudioRecorder:
    def __init__(self, settings, backend=None, device_service: AudioDeviceService | None = None):
        if backend is None:
            import sounddevice as backend
        self.settings, self.backend = settings, backend
        self.device_service = device_service or AudioDeviceService(backend, target_sample_rate=settings.sample_rate)
        self.sensitivity = getattr(settings, "microphone_sensitivity", "normal")

    def test_device(self, requested_index: int | None) -> tuple[bool, str]:
        try:
            resolved = self.device_service.resolve_for_recording(requested_index)
            with self.backend.InputStream(**self._stream_options(resolved, lambda *_args: None)): pass
            note = "16 kHz" if not resolved.requires_resampling else f"{resolved.sample_rate} Hz; audio will be resampled to 16 kHz"
            return True, f"{resolved.name} [{resolved.host_api_name}] opened successfully at {note}."
        except Exception as exc:
            logger.exception("Microphone test failed")
            return False, self._safe_error(exc)

    def record(self, requested_index: int | None, stop_event: Event, level_callback=None, status_callback=None) -> RecordingResult:
        try:
            resolved = self.device_service.resolve_for_recording(requested_index)
        except DeviceResolutionError as exc:
            logger.warning("Microphone resolution failed: %s", exc)
            return RecordingResult(success=False, error_code="invalid_device", message=str(exc))

        chunks: Queue[np.ndarray] = Queue()
        source_rate = resolved.sample_rate
        calibration_target = round(getattr(self.settings, "calibration_seconds", 0.7) * source_rate)
        calibration_samples = 0; calibration_square_sum = 0.0; calibrated = calibration_target <= 0
        calibration_finished_at = monotonic() if calibrated else None
        rms_threshold = self.calculate_rms_threshold(0.0, self.sensitivity)
        peak_threshold = self.peak_threshold(self.sensitivity)
        speech_started = False; consecutive_speech = 0; candidate_samples = 0
        candidate_start_sample = None; speech_start_sample = None; last_speech_sample = None
        trailing_silence_samples = 0; post_calibration_samples = 0
        if status_callback: status_callback("Listening... Please remain quiet while the microphone calibrates.")

        def callback(indata, frames, time_info, status):
            del frames, time_info
            if status: logger.warning("Audio stream status: %s", status)
            chunks.put(np.asarray(indata[:, 0], dtype=np.float32).copy())

        try:
            with self.backend.InputStream(**self._stream_options(resolved, callback)):
                recorded: list[np.ndarray] = []
                while not stop_event.is_set():
                    if post_calibration_samples / source_rate >= self.settings.max_recording_seconds: break
                    try: chunk = chunks.get(timeout=0.1)
                    except Empty:
                        if calibrated and not speech_started and calibration_finished_at is not None and monotonic() - calibration_finished_at >= self.settings.initial_wait_seconds:
                            logger.debug("Speech rejected: initial timeout after calibration")
                            break
                        continue
                    rms = float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0
                    peak = float(np.max(np.abs(chunk))) if chunk.size else 0.0
                    if level_callback: level_callback(rms)
                    if not calibrated:
                        calibration_square_sum += float(np.sum(np.square(chunk, dtype=np.float64)))
                        calibration_samples += len(chunk)
                        if calibration_samples >= calibration_target:
                            noise_floor = float(np.sqrt(calibration_square_sum / max(1, calibration_samples)))
                            rms_threshold = self.calculate_rms_threshold(noise_floor, self.sensitivity)
                            calibrated = True; calibration_finished_at = monotonic()
                            logger.debug("Microphone calibration: noise_floor=%.8f rms_threshold=%.8f sensitivity=%s", noise_floor, rms_threshold, self.sensitivity)
                            if status_callback: status_callback("Listening... Speak your command.")
                        continue

                    frame_start_sample = post_calibration_samples
                    recorded.append(chunk); post_calibration_samples += len(chunk)
                    evidence = rms >= rms_threshold or peak >= peak_threshold
                    logger.debug("VAD frame: rms=%.8f peak=%.8f rms_threshold=%.8f peak_threshold=%.8f evidence=%s", rms, peak, rms_threshold, peak_threshold, evidence)
                    if not speech_started:
                        if evidence:
                            if consecutive_speech == 0: candidate_start_sample = frame_start_sample
                            consecutive_speech += 1; candidate_samples += len(chunk)
                            if consecutive_speech >= 3:
                                speech_started = True; speech_start_sample = candidate_start_sample
                                last_speech_sample = post_calibration_samples; trailing_silence_samples = 0
                        else:
                            consecutive_speech = 0; candidate_samples = 0; candidate_start_sample = None
                            if post_calibration_samples / source_rate >= self.settings.initial_wait_seconds:
                                logger.debug("Speech rejected: no three-frame speech start before post-calibration timeout")
                                break
                    else:
                        if evidence:
                            last_speech_sample = post_calibration_samples; trailing_silence_samples = 0
                        else:
                            trailing_silence_samples += len(chunk)
                            if trailing_silence_samples / source_rate >= self.settings.silence_seconds: break
                audio = np.concatenate(recorded) if recorded else np.empty(0, dtype=np.float32)
        except Exception as exc:
            logger.exception("Audio recording failed for device %s", resolved.identifier)
            code = "invalid_device" if "invalid device" in str(exc).lower() else "audio_stream_error"
            return RecordingResult(success=False, error_code=code, message=self._safe_error(exc))

        original_duration = len(audio) / source_rate
        speech_duration = ((last_speech_sample - speech_start_sample) / source_rate) if speech_start_sample is not None and last_speech_sample is not None else 0.0
        logger.debug("Detected speech duration: %.3f seconds", speech_duration)
        cancelled = stop_event.is_set()
        if speech_duration < self.settings.min_speech_seconds:
            audio.fill(0)
            logger.debug("Speech rejected: duration %.3f below minimum %.3f", speech_duration, self.settings.min_speech_seconds)
            return RecordingResult(success=False, duration=original_duration, original_duration=original_duration, speech_duration=speech_duration, cancelled=cancelled, error_code="no_speech", message="No clear speech was detected. Please try again.")
        pre_padding = round(getattr(self.settings, "pre_speech_padding", 0.25) * source_rate)
        post_padding = round(getattr(self.settings, "post_speech_padding", 0.4) * source_rate)
        trim_start = max(0, speech_start_sample - pre_padding)
        trim_end = min(len(audio), last_speech_sample + post_padding)
        trimmed = audio[trim_start:trim_end].copy()
        audio.fill(0)
        trimmed_duration = len(trimmed) / source_rate
        logger.info("Voice audio trimmed: original_duration=%.3fs trimmed_duration=%.3fs speech_duration=%.3fs", original_duration, trimmed_duration, speech_duration)
        if resolved.requires_resampling:
            audio = self.resample(trimmed, source_rate, self.settings.sample_rate); trimmed.fill(0)
        else:
            audio = trimmed
        if getattr(self.settings, "save_audio", False): self._save_development_audio(audio)
        return RecordingResult(success=True, audio=audio, sample_rate=self.settings.sample_rate, duration=trimmed_duration, original_duration=original_duration, speech_duration=speech_duration, message="Recording completed.")

    @staticmethod
    def calculate_rms_threshold(noise_floor: float, sensitivity: str = "normal") -> float:
        if sensitivity.lower() == "high": return min(0.003, max(0.0008, noise_floor * 3.0))
        return min(0.005, max(0.0015, noise_floor * 4.0))

    @staticmethod
    def peak_threshold(sensitivity: str = "normal") -> float:
        return 0.010 if sensitivity.lower() == "high" else 0.015

    @staticmethod
    def resample(audio: np.ndarray, source_rate: int, target_rate: int = 16000) -> np.ndarray:
        if source_rate == target_rate or audio.size == 0: return audio.astype(np.float32, copy=True)
        output_length = max(1, round(audio.size * target_rate / source_rate))
        return np.interp(np.linspace(0, audio.size - 1, output_length), np.arange(audio.size), audio).astype(np.float32)

    @staticmethod
    def _stream_options(resolved: ResolvedAudioDevice, callback):
        return {"device": resolved.identifier, "channels": 1, "samplerate": resolved.sample_rate, "dtype": "float32", "callback": callback}

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        detail = " ".join(str(exc).split())[:240]
        return f"The selected microphone could not be opened: {detail or type(exc).__name__}."

    def _save_development_audio(self, audio: np.ndarray) -> None:
        directory = self.settings.recordings_path; directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"recording-{int(monotonic() * 1000)}.wav"
        pcm = np.clip(audio, -1.0, 1.0)
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(self.settings.sample_rate)
            output.writeframes((pcm * 32767).astype(np.int16).tobytes())
