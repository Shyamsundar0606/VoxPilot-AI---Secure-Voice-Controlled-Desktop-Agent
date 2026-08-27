from threading import Event
from types import SimpleNamespace

import numpy as np

from app.models import ResolvedAudioDevice
from app.voice.audio_devices import DeviceResolutionError
from app.voice.recorder import AudioRecorder


def settings(**overrides):
    values = dict(sample_rate=100, max_recording_seconds=1.0, initial_wait_seconds=0.1, silence_seconds=0.2, min_speech_seconds=0.2, calibration_seconds=0, microphone_sensitivity="normal", save_audio=False)
    values.update(overrides); return SimpleNamespace(**values)


class Resolver:
    def __init__(self, index=7, rate=100, resample=False, error=None): self.index, self.rate, self.requires_resampling, self.error = index, rate, resample, error
    def resolve_for_recording(self, requested):
        if self.error: raise self.error
        return ResolvedAudioDevice(identifier=self.index, name="Microphone", host_api_name="Windows WASAPI", sample_rate=self.rate, requires_resampling=self.requires_resampling)


class StreamBackend:
    def __init__(self, chunks=(), error=None): self.chunks, self.error, self.calls = chunks, error, []
    def InputStream(self, **kwargs):
        self.calls.append(kwargs); backend = self
        class Stream:
            def __enter__(self):
                if backend.error: raise backend.error
                for chunk in backend.chunks: kwargs["callback"](np.asarray(chunk, dtype=np.float32).reshape(-1, 1), len(chunk), None, None)
                return self
            def __exit__(self, *_args): return False
        return Stream()


def recorder(backend, resolver=None, **setting_values):
    return AudioRecorder(settings(**setting_values), backend, resolver or Resolver())


def test_correct_global_index_passed_to_input_stream():
    backend = StreamBackend(([0.5] * 20, [0.5] * 20, [0.5] * 20, [0.0] * 20))
    result = recorder(backend, Resolver(index=7)).record(1, Event())
    assert result.success and backend.calls[0]["device"] == 7
    assert backend.calls[0]["channels"] == 1 and backend.calls[0]["dtype"] == "float32"


def test_recording_start_and_silence_stop():
    result = recorder(StreamBackend(([0.5] * 20, [0.5] * 20, [0.5] * 20, [0.0] * 10, [0.0] * 10))).record(7, Event())
    assert result.success and result.speech_duration == 0.6


def test_maximum_duration_stop():
    result = recorder(StreamBackend(([0.5] * 20,) * 5), max_recording_seconds=0.6).record(7, Event())
    assert result.success and result.duration == 0.6


def test_empty_and_short_recordings_are_cleared():
    empty = recorder(StreamBackend()).record(7, Event())
    short = recorder(StreamBackend(([0.5] * 10, [0.0] * 20))).record(7, Event())
    assert not empty.success and empty.audio is None
    assert not short.success and short.audio is None


def test_invalid_device_resolution():
    resolver = Resolver(error=DeviceResolutionError("Selected microphone index 4 is stale or disconnected."))
    result = recorder(StreamBackend(), resolver).record(4, Event())
    assert not result.success and result.error_code == "invalid_device" and "stale" in result.message


def test_input_stream_invalid_device_preserves_real_reason():
    backend = StreamBackend(error=RuntimeError("Invalid device [PaErrorCode -9996]"))
    result = recorder(backend).record(7, Event())
    assert not result.success and result.error_code == "invalid_device"
    assert "PaErrorCode -9996" in result.message


def test_resampling_to_16khz():
    audio = np.arange(48000, dtype=np.float32)
    output = AudioRecorder.resample(audio, 48000, 16000)
    assert output.dtype == np.float32 and len(output) == 16000


def test_default_rate_recording_is_resampled_to_target():
    backend = StreamBackend(([0.5] * 40, [0.5] * 40, [0.5] * 40, [0.0] * 40))
    result = recorder(backend, Resolver(rate=200, resample=True)).record(7, Event())
    assert result.success and result.sample_rate == 100 and len(result.audio) == 80
    assert backend.calls[0]["samplerate"] == 200


def test_microphone_test_and_recording_share_resolver_and_stream_options():
    backend = StreamBackend(([0.5] * 20, [0.5] * 20, [0.5] * 20, [0.0] * 20)); resolver = Resolver(index=9, rate=100)
    audio_recorder = recorder(backend, resolver)
    assert audio_recorder.test_device(1)[0]
    assert audio_recorder.record(1, Event()).success
    for call in backend.calls:
        assert call["device"] == 9 and call["samplerate"] == 100 and call["channels"] == 1 and call["dtype"] == "float32"


def test_stop_and_raw_audio_privacy(tmp_path):
    stop = Event(); stop.set()
    stopped = recorder(StreamBackend()).record(7, stop)
    saved = recorder(StreamBackend(([0.5] * 20, [0.5] * 20, [0.5] * 20, [0.0] * 20),), recordings_path=tmp_path).record(7, Event())
    assert stopped.cancelled and not stopped.success
    assert saved.success and list(tmp_path.iterdir()) == []


def measured_recorder(chunks, **overrides):
    backend = StreamBackend(chunks)
    defaults = dict(sample_rate=1000, calibration_seconds=0.7, initial_wait_seconds=0.5, silence_seconds=0.2, min_speech_seconds=0.25, max_recording_seconds=3.0, microphone_sensitivity="normal")
    defaults.update(overrides)
    return recorder(backend, Resolver(rate=defaults["sample_rate"]), **defaults), backend


def calibration_frames(rate=1000, level=0.00003):
    return tuple(([level] * 100 for _ in range(round(rate * 0.7 / 100))))


def test_measured_idle_noise_is_rejected():
    chunks = calibration_frames() + tuple(([0.00003] * 100 for _ in range(5)))
    audio_recorder, _ = measured_recorder(chunks)
    result = audio_recorder.record(7, Event())
    assert not result.success and result.error_code == "no_speech"


def test_measured_speech_rms_is_accepted():
    chunks = calibration_frames() + tuple(([0.0084] * 100 for _ in range(3))) + tuple(([0.0] * 100 for _ in range(2)))
    audio_recorder, _ = measured_recorder(chunks)
    assert audio_recorder.record(7, Event()).success


def test_measured_peak_is_accepted_as_supporting_evidence():
    rate = 10000
    calibration = tuple(([0.00003] * 1000 for _ in range(7)))
    peak_frame = [0.0] * 2000; peak_frame[0] = 0.062
    chunks = calibration + (peak_frame, peak_frame, peak_frame) + ([0.0] * 2000,)
    audio_recorder, _ = measured_recorder(chunks, sample_rate=rate, silence_seconds=0.2, min_speech_seconds=0.4)
    assert audio_recorder.record(7, Event()).success


def test_calibration_audio_is_excluded_and_timeout_resets_after_it():
    chunks = calibration_frames() + tuple(([0.0084] * 100 for _ in range(3))) + tuple(([0.0] * 100 for _ in range(2)))
    audio_recorder, _ = measured_recorder(chunks)
    statuses = []
    result = audio_recorder.record(7, Event(), status_callback=statuses.append)
    assert result.success
    assert len(result.audio) == 500
    assert result.duration == 0.5
    assert "remain quiet" in statuses[0]
    assert statuses[-1] == "Listening... Speak your command."


def test_three_consecutive_frames_trigger_but_one_spike_does_not():
    accepted_chunks = calibration_frames() + tuple(([0.0084] * 100 for _ in range(3))) + tuple(([0.0] * 100 for _ in range(2)))
    accepted, _ = measured_recorder(accepted_chunks)
    assert accepted.record(7, Event()).success
    rejected_chunks = calibration_frames() + ([0.062] + [0.0] * 99,) + tuple(([0.00003] * 100 for _ in range(5)))
    rejected, _ = measured_recorder(rejected_chunks)
    assert not rejected.record(7, Event()).success


def test_normal_and_high_sensitivity_thresholds():
    assert AudioRecorder.calculate_rms_threshold(0.00003, "normal") == 0.0015
    assert AudioRecorder.calculate_rms_threshold(0.002, "normal") == 0.005
    assert AudioRecorder.calculate_rms_threshold(0.00003, "high") == 0.0008
    assert AudioRecorder.calculate_rms_threshold(0.002, "high") == 0.003


def long_recording_chunks():
    # Five seconds quiet, 1.7 seconds speech, then 8.3 seconds trailing silence.
    return tuple(([0.0] * 10 for _ in range(50))) + tuple(([0.0084] * 10 for _ in range(17))) + tuple(([0.0] * 10 for _ in range(83)))


def test_speech_boundary_trimming_sends_short_audio_not_full_buffer():
    audio_recorder = recorder(
        StreamBackend(long_recording_chunks()), Resolver(rate=100),
        calibration_seconds=0, initial_wait_seconds=6, silence_seconds=20,
        max_recording_seconds=15, min_speech_seconds=0.4,
        pre_speech_padding=0.25, post_speech_padding=0.4,
    )
    result = audio_recorder.record(7, Event())
    assert result.success
    assert result.original_duration == 15.0
    assert result.duration == 2.35
    assert len(result.audio) == 235


def test_pre_and_post_padding_and_trailing_silence_removal():
    audio_recorder = recorder(
        StreamBackend(long_recording_chunks()), Resolver(rate=100),
        calibration_seconds=0, initial_wait_seconds=6, silence_seconds=20,
        max_recording_seconds=15, min_speech_seconds=0.4,
        pre_speech_padding=0.25, post_speech_padding=0.4,
    )
    result = audio_recorder.record(7, Event())
    speech_indices = np.flatnonzero(result.audio > 0.001)
    assert speech_indices[0] == 25
    assert len(result.audio) - 1 - speech_indices[-1] == 40
    assert result.duration < result.original_duration
