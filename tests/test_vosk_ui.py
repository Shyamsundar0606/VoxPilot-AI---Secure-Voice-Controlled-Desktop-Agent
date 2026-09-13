from unittest.mock import Mock
from PySide6.QtCore import QThread
from tests.test_ui_voice_signals import ui, finish_recording, finish_transcription
from app.voice.vosk_decoder import MESSAGES
import pytest


def test_wake_start_does_not_check_or_download_whisper(ui):
    window, _ = ui
    window.transcriber.model_cached.side_effect = AssertionError('Whisper queried by wake path')
    window.wake_toggle.setChecked(True)
    assert window._wake_worker is not None
    window.transcriber.model_cached.assert_not_called()
    window.transcriber.transcribe.assert_not_called()


def test_missing_model_shows_setup_in_ui_without_erasing_result(ui):
    window, _ = ui
    window.result_panel.setPlainText('Previous PDF summary')
    window.wake_toggle.setChecked(True)
    window._wake_worker.setup_failed.emit(MESSAGES['missing_model'])
    assert not window.wake_toggle.isChecked()
    assert 'VOSK_MODEL_PATH' in window.wake_notice.text()
    assert window.status.text() == 'Status: Failed'
    assert window.result_panel.toPlainText() == 'Previous PDF summary'
    assert not window._wake_retry.isActive()


def test_disconnected_microphone_retries_one_listener(ui):
    window, _ = ui
    window.wake_toggle.setChecked(True)
    old, thread = window._wake_worker, window._wake_thread
    old.failed.emit('Microphone disconnected')
    thread.finished.emit()
    assert window._wake_retry.isActive()
    window._wake_retry.timeout.emit()
    current = window._wake_worker
    assert current is not None and current is not old
    old.setup_failed.emit('stale failure')
    assert window.wake_toggle.isChecked()
    window._start_wake_listener()
    assert window._wake_worker is current


def test_manual_mic_waits_for_wake_teardown(ui):
    window, _ = ui
    window.wake_toggle.setChecked(True)
    thread = window._wake_thread
    window.start_voice_command()
    assert window._wake_cancel.is_set() and window._voice_thread is None
    # The queued transition is executed only after wake teardown; invoke it
    # explicitly since this fixture suppresses real thread starts.
    thread.finished.emit()
    window.start_voice_command()
    assert window._voice_thread is not None and window._wake_thread is None


def test_sensitivity_updates_both_audio_paths(ui):
    window, _ = ui
    window._set_microphone_sensitivity('high')
    assert window.recorder.sensitivity == 'high'
    assert window.wake_controller.sensitivity == 'high'


def test_close_releases_persistent_vosk_decoder(ui):
    window, _ = ui
    window.close()
    window.wake_controller.shutdown.assert_called_once()


def test_silent_device_recovery_retry_cancelled_by_stop(ui):
    window, _ = ui
    window.microphone_settings.selected_device = Mock(return_value=None)
    window.wake_toggle.setChecked(True)
    assert window._wake_retry.isActive() and window._wake_worker is None
    window.stop()
    assert not window._wake_retry.isActive()
    window._wake_retry.timeout.emit()
    assert window._wake_worker is None


def test_toggle_cancels_already_detected_old_activation(ui):
    window, _ = ui
    window._after_tts = Mock()
    window.wake_toggle.setChecked(True)
    worker, thread = window._wake_worker, window._wake_thread
    worker.activation.emit('hello')
    window.wake_toggle.setChecked(False); window.wake_toggle.setChecked(True)
    thread.finished.emit()
    window._after_tts.assert_not_called()
    assert window._voice_thread is None


@pytest.mark.parametrize('failed', [False, True])
def test_streaming_vosk_through_real_qt_command_cycle(failed):
    from threading import Event
    from time import monotonic, sleep
    from types import SimpleNamespace
    import numpy as np
    from tests.test_wake_word import controller_result
    from tests.test_runtime import _window, _app, _result
    from app.models import RecordingResult, TranscriptionResult, Status
    from app.agent.router import CommandRouter
    from app.voice.voice_controller import VoiceCommandController
    from app.voice.recorder import AudioRecorder
    window = _window()
    window.settings.wake_word_cooldown = 0
    controller, _, stream, _ = controller_result()
    resumed = Event(); calls = []
    def feed(*_):
        calls.append(1)
        if len(calls) == 1: return 'hello'
        resumed.set(); return ''
    controller.decoder.feed.side_effect = feed
    window.wake_controller = controller
    window.device_service = SimpleNamespace(store=None)
    window.microphone_settings = SimpleNamespace(selected_device=lambda: 7, refresh=Mock())
    def record(*_):
        assert not stream.active and not AudioRecorder._microphone_lock.locked()
        return RecordingResult(success=True, audio=np.ones(100), speech_duration=1)
    window.recorder = Mock(record=Mock(side_effect=record))
    window.transcriber = Mock(model_cached=Mock(return_value=True), transcribe=Mock(return_value=
        TranscriptionResult(success=True, text='Open Google', model_used='mock-command-whisper')))
    router = Mock(wraps=CommandRouter())
    window.voice_controller = VoiceCommandController(router, window.executor)
    window.executor.execute.return_value = _result(Status.FAILED if failed else Status.COMPLETED)
    def speak(text):
        assert not stream.active and not AudioRecorder._microphone_lock.locked()
    window.tts.speak.side_effect = speak
    try:
        window.wake_toggle.setChecked(True)
        deadline = monotonic() + 3
        while not resumed.is_set() and monotonic() < deadline:
            _app().processEvents(); sleep(.001)
        assert resumed.is_set()
        window.recorder.record.assert_called_once()
        window.transcriber.transcribe.assert_called_once()
        router.route.assert_called_once_with('Open Google')
        window.executor.execute.assert_called_once_with('Open Google')
        assert window.tts.speak.call_args_list[0].args == ('Yes, how can I help you?',)
        assert window.result_panel.toPlainText() == window.executor.execute.return_value.result_message
        assert window.status.text() == 'Status: Wake-word listening'
        window.repository.add.assert_called_once()
    finally:
        window.stop()
        deadline = monotonic() + 3
        while window._wake_thread is not None and monotonic() < deadline:
            _app().processEvents(); sleep(.001)
        assert window._wake_thread is None and not stream.active
        window.close()
