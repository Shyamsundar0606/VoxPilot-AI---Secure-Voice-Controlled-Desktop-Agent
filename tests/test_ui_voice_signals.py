"""Exercise the production Qt connections without hardware or scheduled workers."""
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QThread

from app.agent.router import CommandRouter
from app.models import RecordingResult, TranscriptionResult, ExecutionResult, Status
from app.ui.workers import WakeWordWorker, TranscriptionWorker, VoiceSource
from app.voice.voice_controller import VoiceCommandController
from tests.test_runtime import _window


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.setattr(QThread, "start", lambda self: None)
    window = _window()
    window.device_service = SimpleNamespace(store=None)
    window.microphone_settings = SimpleNamespace(selected_device=lambda: 2, refresh=Mock())
    window.recorder = Mock()
    window.transcriber = Mock(model_cached=Mock(return_value=True))
    window.wake_controller = Mock()
    router = Mock(wraps=CommandRouter())
    window.voice_controller = VoiceCommandController(router, window.executor)
    window._voice_failure = Mock(wraps=window._voice_failure)
    yield window, router
    window.stop()
    window._wake_thread = window._voice_thread = window._active_thread = None
    window.close()


def finish_recording(window):
    worker, thread = window._voice_worker, window._voice_thread
    worker.finished.emit(RecordingResult(success=True, audio=np.ones(100), speech_duration=1))
    thread.finished.emit()


def finish_transcription(window, text):
    worker, thread = window._voice_worker, window._voice_thread
    worker.result_ready.emit(TranscriptionResult(success=True, text=text, model_used="fake"), worker.source)
    thread.finished.emit()


def test_wake_signal_then_only_second_phrase_routes_and_is_stored(ui):
    window, router = ui
    window._after_tts = Mock()
    window.wake_toggle.setChecked(True)
    worker, thread = window._wake_worker, window._wake_thread
    worker.activation.emit("Hello Google")
    window.tts.speak.assert_not_called()
    worker.activation.emit("HELLO!")
    worker.activation.emit("Hello")  # Duplicate delivery must be idempotent.
    assert window.status.text() == "Status: Wake detected"
    router.route.assert_not_called()
    window.executor.execute.assert_not_called()
    window.repository.add.assert_not_called()
    assert window.history.count() == 0
    window._voice_failure.assert_not_called()
    window.tts.speak.assert_called_once_with("Yes, how can I help you?")
    thread.finished.emit()
    window._after_tts.assert_called_once()
    window._after_tts.call_args.args[0]()
    assert window.status.text() == "Status: Command listening"
    assert window._voice_source == VoiceSource.WAKE_COMMAND
    first_capture = window._voice_worker
    worker.activation.emit("Hello")  # Old worker cannot initiate another capture.
    assert window._voice_worker is first_capture
    finish_recording(window)
    finish_transcription(window, "Open Google")
    router.route.assert_called_once_with("Open Google")
    window._active_worker.finished.emit(ExecutionResult(
        original_command="Open Google", normalized_command="open google",
        selected_tool="open_url", status=Status.COMPLETED, result_message="Google is now open.",
    ))
    window.repository.add.assert_called_once()
    assert window.repository.add.call_args.args[0].original_command == "Open Google"
    assert window.history.count() == 1
    assert "Hello" not in window.history.item(0).text()


def test_restarts_keep_one_worker_and_ignore_stale_signals(ui):
    window, router = ui
    window.wake_toggle.setChecked(True)
    for _ in range(3):
        old_worker, old_thread = window._wake_worker, window._wake_thread
        window.wake_toggle.setChecked(False)
        window.wake_toggle.setChecked(True)
        assert window._wake_worker is old_worker  # Wait for teardown first.
        old_worker.activation.emit("Hello")
        window.tts.speak.assert_not_called()
        old_thread.finished.emit()
        window._start_wake_listener()
        current = window._wake_worker
        assert current is not old_worker
        window._start_wake_listener()
        assert window._wake_worker is current
        old_worker.activation.emit("Hello")
        old_worker.failed.emit("stale error")
        old_thread.finished.emit()
        assert window._wake_worker is current
        window.tts.speak.assert_not_called()
    window._wake_worker.activation.emit("Hello")
    window.tts.speak.assert_called_once()
    router.route.assert_not_called()


def test_manual_result_uses_explicit_source_and_ignores_stale_worker(ui):
    window, router = ui
    window.start_voice_command()
    assert window._voice_source == VoiceSource.MANUAL
    finish_recording(window)
    result = TranscriptionResult(success=True, text="Hello", model_used="fake")
    stale = TranscriptionWorker(Mock(), None, Event())
    stale.result_ready.connect(window._store_transcription_result)
    stale.result_ready.emit(result, VoiceSource.MANUAL)
    assert window._voice_result is None
    window._voice_worker.result_ready.emit(result, VoiceSource.WAKE)
    assert window._voice_result is None
    finish_transcription(window, "Open Google")
    router.route.assert_called_once_with("Open Google")


def directory_result(message="resume.pdf\nApplications/", store_history=False):
    return ExecutionResult(original_command="List files in Documents", normalized_command="list files in documents",
        selected_tool="list_directory", status=Status.COMPLETED, result_message=message, store_history=store_history)


@pytest.mark.parametrize("store_history", [False, True])
def test_wake_resumption_preserves_completed_result(ui, store_history):
    window, _ = ui
    window.wake_toggle.blockSignals(True)
    window.wake_toggle.setChecked(True)
    window.wake_toggle.blockSignals(False)
    window._after_tts = lambda callback: callback()
    result = directory_result(store_history=store_history)
    window._wake_command_pending = True
    window._complete(result)
    window._command_finished()
    assert window._wake_worker is not None
    assert window.status.text() == "Status: Wake-word listening"
    assert window.result_panel.toPlainText() == result.result_message
    window._wake_worker.state_changed.emit("Processing")
    window._wake_worker.state_changed.emit("Wake-word listening")
    assert window.result_panel.toPlainText() == result.result_message


def test_listing_survives_next_activation_and_capture_until_new_result(ui):
    window, _ = ui
    result = directory_result()
    window._complete(result)
    window.wake_toggle.setChecked(True)
    worker, thread = window._wake_worker, window._wake_thread
    window._after_tts = lambda callback: callback()
    worker.activation.emit("Hello")
    assert window.status.text() == "Status: Wake detected"
    assert window.result_panel.toPlainText() == result.result_message
    thread.finished.emit()
    assert window.status.text() == "Status: Command listening"
    window._voice_worker.status_changed.emit("Listening... Speak your command.")
    assert window.result_panel.toPlainText() == result.result_message
    finish_recording(window)
    assert window.status.text() == "Status: Processing"
    assert window.result_panel.toPlainText() == result.result_message
    finish_transcription(window, "Open Google")
    assert window.result_panel.toPlainText() == result.result_message
    window._active_worker.finished.emit(directory_result("Next command result"))
    assert window.result_panel.toPlainText() == "Next command result"


def test_wake_failure_and_stop_do_not_erase_listing(ui):
    window, _ = ui
    result = directory_result()
    window._complete(result)
    window.wake_toggle.setChecked(True)
    window._wake_worker.failed.emit("Microphone unavailable")
    assert window.status.text() == "Status: Failed"
    assert window.status.toolTip() == "Microphone unavailable"
    assert window.result_panel.toPlainText() == result.result_message
    window.stop()
    assert window.result_panel.toPlainText() == result.result_message
