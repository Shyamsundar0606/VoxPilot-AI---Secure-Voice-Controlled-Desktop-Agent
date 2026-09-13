import os
from types import SimpleNamespace
from unittest.mock import Mock
from threading import Event
from time import monotonic, sleep
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.models import ExecutionResult, Status
from app.models import RecordingResult, TranscriptionResult
from app.ui.main_window import MainWindow
from app.ui.workers import CommandWorker


def _app():
    return QApplication.instance() or QApplication([])


def _result(status=Status.COMPLETED):
    return ExecutionResult(
        original_command="What time is it?", normalized_command="what time is it",
        selected_tool="current_time", status=status,
        result_message="The current time is 6:30 PM.",
    )


def _window(executor=None, repository=None, tts=None):
    _app()
    settings = SimpleNamespace(app_name="VoxPilot AI", assistant_name="Shyam", wake_word_cooldown=1.5, whisper_model_size="base.en")
    repository = repository or Mock(recent=Mock(return_value=[]))
    tts = tts or SimpleNamespace(enabled=False, speak=Mock(return_value=False))
    return MainWindow(settings, executor or Mock(), repository, tts)


def _wait_for_worker(window, timeout_ms=1000):
    loop = QEventLoop()
    timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit)
    thread = window._active_thread
    thread.finished.connect(loop.quit)
    timer.start(timeout_ms); loop.exec()
    assert window._active_thread is None


def test_successful_command_leaves_processing():
    executor = Mock(); executor.execute.return_value = _result()
    window = _window(executor=executor)
    window.input.setText("What time is it?"); window.execute_command(); _wait_for_worker(window)
    assert window.status.text() == "Status: Completed"
    assert "6:30 PM" in window.result_panel.toPlainText()


def test_worker_exception_emits_failed_result():
    executor = Mock(); executor.execute.side_effect = RuntimeError("unexpected")
    worker = CommandWorker(executor, "What time is it?")
    emitted = []; worker.finished.connect(emitted.append); worker.run()
    assert emitted[0].status == Status.FAILED


def test_executor_exception_updates_ui_to_failed():
    executor = Mock(); executor.execute.side_effect = RuntimeError("unexpected")
    window = _window(executor=executor)
    window.input.setText("What time is it?"); window.execute_command(); _wait_for_worker(window)
    assert window.status.text() == "Status: Failed"
    assert "could not be completed safely" in window.result_panel.toPlainText()


def test_database_exception_still_leaves_processing():
    executor = Mock(); executor.execute.return_value = _result()
    repository = Mock(); repository.recent.return_value = []; repository.add.side_effect = RuntimeError("database locked")
    window = _window(executor=executor, repository=repository)
    window.input.setText("What time is it?"); window.execute_command(); _wait_for_worker(window)
    assert window.status.text() == "Status: Completed"
    assert "History could not be saved" in window.result_panel.toPlainText()


def test_tts_exception_still_leaves_processing():
    executor = Mock(); executor.execute.return_value = _result()
    tts = SimpleNamespace(enabled=True, speak=Mock(side_effect=RuntimeError("tts broke")))
    window = _window(executor=executor, tts=tts)
    window.input.setText("What time is it?"); window.execute_command(); _wait_for_worker(window)
    assert window.status.text() == "Status: Completed"


def test_stop_returns_idle_and_prevents_second_worker():
    window = _window()
    active = Mock(); window._active_thread = active
    window.input.setText("Help"); window.execute_command()
    assert not window.executor.execute.called
    window.stop()
    active.requestInterruption.assert_called_once()
    assert window.status.text() == "Status: Idle"


def test_recording_failure_exits_listening():
    window = _window(); window._voice_phase = "recording"
    window._voice_result = RecordingResult(success=False, error_code="no_speech", message="No speech")
    window._voice_thread_finished()
    assert window.status.text() == "Status: Failed"


def test_transcription_failure_exits_processing():
    window = _window(); window._voice_phase = "transcribing"
    window._voice_result = TranscriptionResult(success=False, model_used="base.en", error_code="timeout", message="Timed out")
    window._voice_thread_finished()
    assert window.status.text() == "Status: Failed"


def test_manual_microphone_cancels_wake_listener_before_starting():
    window = _window(); wake_thread = Mock(); window._wake_thread = wake_thread
    window.start_voice_command()
    assert window._pending_action == "manual"
    assert window._wake_cancel.is_set()
    wake_thread.requestInterruption.assert_called_once()


def test_typed_command_cancels_wake_listener_before_execution():
    window = _window(); wake_thread = Mock(); window._wake_thread = wake_thread
    window.input.setText("Help"); window.execute_command()
    assert window._pending_action == "typed"
    assert not window.executor.execute.called


def test_wake_acknowledgement_has_tts_cooldown():
    tts = SimpleNamespace(enabled=True, timeout=8.0, speak=Mock(), is_busy=Mock(return_value=True))
    window = _window(tts=tts); window._wake_detected()
    tts.speak.assert_called_once_with("Yes, how can I help you?")
    assert window.status.text() == "Status: Wake detected"
    assert window._speech_guard_ms("Yes, how can I help you?") >= 1500
    callback = Mock(); window._after_tts(callback)
    callback.assert_not_called()


def test_existing_wake_thread_prevents_duplicate_listener():
    window = _window(); existing = Mock(); window._wake_thread = existing
    window._start_wake_listener()
    assert window._wake_thread is existing


def test_wake_mode_resumes_after_wake_initiated_command_finishes():
    window = _window()
    window.wake_toggle.blockSignals(True); window.wake_toggle.setChecked(True); window.wake_toggle.blockSignals(False)
    window._wake_command_pending = True
    window._active_thread = Mock()
    window._after_tts = Mock()
    window._command_finished()
    assert not window._wake_command_pending
    window._after_tts.assert_called_once_with(window._start_wake_listener)


def test_stop_disables_wake_mode_and_cancels_listener():
    window = _window(); window.wake_toggle.blockSignals(True); window.wake_toggle.setChecked(True); window.wake_toggle.blockSignals(False)
    thread = Mock(); window._wake_thread = thread
    window.stop()
    assert not window.wake_toggle.isChecked()
    assert window._wake_cancel.is_set()


def test_close_requests_clean_wake_shutdown():
    window = _window(); thread = Mock(); window._wake_thread = thread
    event = Mock(); window.closeEvent(event)
    assert window._wake_cancel.is_set()
    thread.requestInterruption.assert_called_once()
    event.ignore.assert_called_once()


def test_stop_invalidates_pending_cooldown(monkeypatch):
    window = _window()
    callbacks = []
    monkeypatch.setattr(QTimer, "singleShot", lambda delay, callback: callbacks.append(callback))
    capture = Mock()
    window._after_tts(capture)
    window.stop()
    for callback in callbacks: callback()
    capture.assert_not_called()


def test_cancelled_recording_buffer_is_cleared():
    import numpy as np
    window = _window()
    audio = np.ones(100, dtype=np.float32)
    window._voice_result = RecordingResult(success=True, audio=audio)
    window._cancelled = True
    window._voice_thread_finished()
    assert not audio.any()


def test_microphone_test_does_not_overlap_listener():
    window = _window()
    window.recorder = Mock()
    window._wake_thread = Mock()
    window._test_microphone(1)
    window.recorder.test_device.assert_not_called()


@pytest.mark.parametrize("command", ["Open Google.", "Delete my files"])
def test_real_qt_wake_cycle_consumes_activation_and_captures_once(command):
    import numpy as np
    from app.voice.voice_controller import VoiceCommandController
    from app.agent.router import CommandRouter
    from app.models import WakeWordResult

    window = _window()
    window.settings.wake_word_cooldown = 0
    resumed = Event()
    wake_calls = []

    class Wake:
        def listen_once(self, device, cancel, *callbacks):
            wake_calls.append(1)
            if len(wake_calls) == 1:
                return WakeWordResult(detected=True)
            resumed.set()
            cancel.wait(2)
            return WakeWordResult(cancelled=True)

    window.wake_controller = Wake()
    window.device_service = SimpleNamespace(store=None)
    window.microphone_settings = SimpleNamespace(selected_device=lambda: 2)
    window.recorder = Mock()
    window.recorder.record.return_value = RecordingResult(success=True, audio=np.ones(100), speech_duration=1)
    window.transcriber = Mock()
    window.transcriber.model_cached.return_value = True
    window.transcriber.transcribe.return_value = TranscriptionResult(success=True, text=command, model_used="fake")
    window.voice_controller = VoiceCommandController(CommandRouter(), window.executor)
    window.executor.execute.return_value = _result()
    window.wake_toggle.setChecked(True)
    assert window.wake_toggle.text() == 'Wake-word mode: "Hello"'
    try:
        deadline = monotonic() + 3
        while not resumed.is_set() and monotonic() < deadline:
            _app().processEvents(); sleep(0.001)
        assert resumed.is_set()
        window.recorder.record.assert_called_once()
        window.transcriber.transcribe.assert_called_once()
        if command == "Open Google.":
            window.executor.execute.assert_called_once_with(command)
            window.repository.add.assert_called_once()
        else:
            window.executor.execute.assert_not_called()
            window.repository.add.assert_not_called()
        assert "Hello" not in window.command_panel.toPlainText()
    finally:
        window.stop()
        deadline = monotonic() + 3
        while window._wake_thread is not None and monotonic() < deadline:
            _app().processEvents(); sleep(0.001)
        assert window._wake_thread is None
        window.close()
