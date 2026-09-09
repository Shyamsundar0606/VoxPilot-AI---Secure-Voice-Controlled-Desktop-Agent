from threading import Event
from unittest.mock import Mock

import numpy as np
import pytest

from app.models import RecordingResult, TranscriptionResult
from app.ui.workers import WakeWordWorker
from app.voice.wake_word import WakeWordController, is_wake_phrase, normalize_wake_text
from app.agent.router import CommandRouter
from app.voice.voice_controller import VoiceCommandController


@pytest.mark.parametrize("text", ["Hello", "hello", "HELLO!", "Hello.", "  hello  ", "\t HELLO!\n"])
def test_wake_phrase_detection_and_normalization(text):
    assert is_wake_phrase(text)
    assert normalize_wake_text(text) == "hello"


@pytest.mark.parametrize("text", ["Hey Shyam", "Hello Google", "Hello Shyam", "Hey Sam", "Open Chrome", "Shyam", "", "please hello", "hello hello"])
def test_non_wake_speech_is_ignored(text):
    assert not is_wake_phrase(text)
    controller, _, _ = controller_result(text)
    assert not controller.listen_once(2, Event()).detected


def controller_result(text="Hello"):
    recorder = Mock(); recorder.record.return_value = RecordingResult(success=True, audio=np.ones(100, dtype=np.float32), duration=1, speech_duration=1)
    transcriber = Mock(); transcriber.transcribe.return_value = TranscriptionResult(success=True, text=text, model_used="base.en")
    return WakeWordController(recorder, transcriber), recorder, transcriber


def test_wake_phrase_is_activation_not_command_execution():
    controller, _, _ = controller_result()
    assert controller.listen_once(2, Event()).detected
    assert not hasattr(controller, "executor")


def test_non_wake_transcription_is_not_detected():
    controller, _, _ = controller_result("Open Chrome")
    assert not controller.listen_once(2, Event()).detected


@pytest.mark.parametrize("error_code", ["empty_transcription", "low_confidence", "no_audio", "audio_too_short"])
def test_unclear_speech_window_is_ignored_without_stopping_listener(error_code):
    controller, _, transcriber = controller_result()
    transcriber.transcribe.return_value = TranscriptionResult(success=False, model_used="base.en", error_code=error_code, message="Unclear")
    result = controller.listen_once(2, Event())
    assert not result.detected and result.error_code is None


def test_wake_detection_is_followed_by_exactly_one_safe_command():
    controller, _, _ = controller_result("Hello")
    router = Mock(wraps=CommandRouter())
    repository = Mock()
    assert controller.listen_once(2, Event()).detected
    router.route.assert_not_called()
    repository.add.assert_not_called()
    command, error = VoiceCommandController(router, Mock()).approved_command(
        TranscriptionResult(success=True, text="open google", model_used="base.en")
    )
    assert command == "open google" and error is None
    router.route.assert_called_once_with("open google")
    assert all(call.args != ("Hello",) for call in router.route.call_args_list)
    repository.add.assert_not_called()


def test_successful_window_buffer_is_cleared():
    controller, recorder, _ = controller_result()
    audio = recorder.record.return_value.audio
    controller.listen_once(2, Event())
    assert np.count_nonzero(audio) == 0


def test_exception_clears_wake_buffer():
    controller, recorder, transcriber = controller_result()
    audio = recorder.record.return_value.audio
    transcriber.transcribe.side_effect = RuntimeError("failed")
    with pytest.raises(RuntimeError):
        controller.listen_once(2, Event())
    assert recorder.record.return_value.audio is None
    assert not audio.any()


def test_stop_cancellation_skips_microphone():
    controller, recorder, _ = controller_result(); cancel = Event(); cancel.set()
    assert controller.listen_once(2, cancel).cancelled
    recorder.record.assert_not_called()


def test_microphone_failure_is_recoverable_and_buffer_cleared():
    audio = np.ones(20, dtype=np.float32)
    recorder = Mock(); recorder.record.return_value = RecordingResult(success=False, audio=audio, error_code="invalid_device", message="Disconnected")
    result = WakeWordController(recorder, Mock()).listen_once(7, Event())
    assert result.error_code == "invalid_device"
    assert np.count_nonzero(audio) == 0


def test_worker_detected_and_finished_signals():
    controller = Mock(); controller.listen_once.return_value.detected = True
    controller.listen_once.return_value.cancelled = False; controller.listen_once.return_value.error_code = None
    worker = WakeWordWorker(controller, 2, Event()); events = []
    worker.detected.connect(lambda: events.append("detected")); worker.finished.connect(lambda: events.append("finished")); worker.run()
    assert events == ["detected", "finished"]


def test_worker_cancellation_finishes_without_detection():
    controller = Mock(); controller.listen_once.return_value.cancelled = True
    controller.listen_once.return_value.error_code = None; controller.listen_once.return_value.detected = False
    worker = WakeWordWorker(controller, 2, Event()); events = []
    worker.detected.connect(lambda: events.append("detected")); worker.finished.connect(lambda: events.append("finished")); worker.run()
    assert events == ["finished"]
