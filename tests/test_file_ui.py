from time import monotonic, sleep
from unittest.mock import Mock

from PySide6.QtCore import QThread

from tests.test_filesystem import fs
from tests.test_file_confirmations import executor_for, propose
from tests.test_runtime import _window, _app
from app.models import RecordingResult, TranscriptionResult


def wait_idle(window):
    deadline = monotonic() + 3
    while window._active_thread is not None and monotonic() < deadline:
        _app().processEvents(); sleep(0.001)
    assert window._active_thread is None


def test_panel_confirms_exact_proposal_in_worker(fs):
    service, docs, _ = fs
    window = _window(executor=executor_for(service))
    window.input.setText("Create a folder called Internship Applications in Documents")
    window.execute_command(); wait_idle(window)
    assert window._confirmation is not None
    assert str(docs) in window.confirmation_label.text()
    assert not (docs / "Internship Applications").exists()
    window.confirm_button.click(); wait_idle(window)
    assert (docs / "Internship Applications").exists()
    window.repository.add.assert_not_called()
    window.close()


def test_stop_cancels_confirmation(fs):
    service, docs, _ = fs
    window = _window(executor=executor_for(service))
    result = propose(window.executor)
    window._complete(result)
    window.stop()
    assert window._confirmation is None
    window.executor.confirm(result.confirmation["token"])
    assert not (docs / "Internship Applications").exists()
    window.close()


def test_timeout_and_cancel_resume_wake(fs):
    service, docs, _ = fs
    window = _window(executor=executor_for(service))
    window.wake_toggle.blockSignals(True); window.wake_toggle.setChecked(True); window.wake_toggle.blockSignals(False)
    window._after_tts = Mock()
    window._complete(propose(window.executor))
    window._start_wake_listener()
    assert window._wake_thread is None
    window._confirmation_timer.timeout.emit()
    assert window._confirmation is None
    window._after_tts.assert_called_once_with(window._start_wake_listener)
    assert not (docs / "Internship Applications").exists()
    window.close()


def test_unrelated_command_invalidates_pending_write(fs):
    service, docs, _ = fs
    window = _window(executor=executor_for(service))
    result = propose(window.executor)
    window._complete(result)
    window.input.setText("Hello"); window.execute_command(); wait_idle(window)
    assert window._confirmation is None
    window.executor.confirm(result.confirmation["token"])
    assert not (docs / "Internship Applications").exists()
    window.close()


def test_exact_voice_confirmation_uses_same_pending_token(fs):
    service, docs, _ = fs
    window = _window(executor=executor_for(service))
    window._complete(propose(window.executor))
    window._voice_confirmation_token = window._confirmation["token"]
    window._voice_phase = "transcribing"
    window._voice_result = TranscriptionResult(success=True, text="Confirm", model_used="fake")
    window._voice_thread_finished(); wait_idle(window)
    assert (docs / "Internship Applications").exists()
    window.close()


def test_stale_voice_confirmation_cannot_confirm_new_proposal(fs):
    service, docs, _ = fs
    window = _window(executor=executor_for(service))
    window._complete(propose(window.executor))
    window._voice_confirmation_token = window._confirmation["token"]
    window._cancel_confirmation(resume=False)
    window._complete(propose(window.executor))
    window._voice_phase = "transcribing"
    window._voice_result = TranscriptionResult(success=True, text="Confirm", model_used="fake")
    window._voice_thread_finished()
    assert not (docs / "Internship Applications").exists()
    assert window._active_thread is None
    window.close()


def test_file_policy_runs_off_gui_thread(fs, monkeypatch):
    from threading import get_ident
    service, _, _ = fs
    threads = []
    original = service.roots.resolve
    def resolve(*args, **kwargs):
        threads.append(get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(service.roots, "resolve", resolve)
    window = _window(executor=executor_for(service))
    window.input.setText("List folders in Documents")
    window.execute_command(); wait_idle(window)
    assert threads and all(thread != get_ident() for thread in threads)
    window.close()
