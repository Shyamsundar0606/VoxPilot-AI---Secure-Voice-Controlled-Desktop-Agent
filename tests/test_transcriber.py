from threading import Event
from time import sleep
from types import SimpleNamespace

import numpy as np

from app.models import RecordingResult
from app.voice.transcriber import SpeechTranscriber


def settings(**overrides):
    values = dict(whisper_model_size="base.en", whisper_device="auto", whisper_compute_type="int8", whisper_language="en", whisper_beam_size=5, transcription_timeout=0.1, min_language_probability=0.5, min_speech_seconds=0.4)
    values.update(overrides); return SimpleNamespace(**values)


def recording(seconds=1.0):
    return RecordingResult(success=True, audio=np.ones(16000, dtype=np.float32), duration=seconds, speech_duration=seconds)


class Model:
    def __init__(self, text="Open Chrome", probability=0.99, error=None, delay=0): self.text, self.probability, self.error, self.delay, self.audio_references = text, probability, error, delay, []
    def transcribe(self, audio, **_kwargs):
        self.audio_references.append(audio)
        if self.delay: sleep(self.delay)
        if self.error: raise self.error
        return iter([SimpleNamespace(text=self.text)]), SimpleNamespace(language="en", language_probability=self.probability)


def transcriber(model, **overrides): return SpeechTranscriber(settings(**overrides), model_factory=lambda: model, allow_download=True)


def test_successful_transcription_and_audio_cleared():
    model = Model(); source = recording(); result = transcriber(model).transcribe(source)
    assert result.success and result.text == "Open Chrome" and result.language == "en"
    assert source.audio is None
    assert np.count_nonzero(model.audio_references[0]) == 0


def test_empty_transcription():
    result = transcriber(Model(text="  ")).transcribe(recording())
    assert not result.success and result.error_code == "empty_transcription"


def test_low_confidence_transcription():
    result = transcriber(Model(probability=0.2)).transcribe(recording())
    assert not result.success and result.error_code == "low_confidence"


def test_whisper_exception():
    result = transcriber(Model(error=RuntimeError("broken"))).transcribe(recording())
    assert not result.success and result.error_code == "model_unavailable"


def test_whisper_timeout():
    result = transcriber(Model(delay=0.2), transcription_timeout=0.01).transcribe(recording())
    assert not result.success and result.error_code == "timeout"


def test_short_audio_rejected():
    source = recording(0.1); result = transcriber(Model()).transcribe(source)
    assert not result.success and result.error_code == "audio_too_short"
    assert source.audio is None


def test_cancelled_transcription():
    cancel = Event(); cancel.set()
    source = recording(); result = transcriber(Model()).transcribe(source, cancel)
    assert not result.success and result.cancelled
    assert source.audio is None


def test_loaded_model_is_reused_between_commands():
    model = Model(); calls = []
    speech = SpeechTranscriber(settings(), model_factory=lambda: calls.append(1) or model, allow_download=True)
    assert speech.transcribe(recording()).success
    assert speech.transcribe(recording()).success
    assert len(calls) == 1
