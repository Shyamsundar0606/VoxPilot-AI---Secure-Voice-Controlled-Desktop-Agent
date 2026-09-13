from dataclasses import replace
from threading import Event, get_ident
from time import monotonic, sleep
from unittest.mock import Mock

from PySide6.QtCore import QTimer, QThread

from app.agent.executor import CommandExecutor
from app.models import Status, TranscriptionResult
from app.ui.workers import CommandWorker, CommandSignalRelay
from tests.test_runtime import _window, _app
from tests.test_filesystem import fs
from tests.test_documents import service_for, write_pdf, request, SUMMARY
from tests.test_file_ui import wait_idle
from tests.test_ui_voice_signals import ui, finish_recording, finish_transcription


def setup_window(fs, selection=False):
    write_pdf(fs[1] / "report.pdf")
    if selection: write_pdf(fs[2] / "report.pdf")
    service = service_for(fs)
    return _window(executor=CommandExecutor(documents=service)), service


def test_real_command_worker_summary_kept_on_resume(fs):
    window, service = setup_window(fs)
    router = Mock(wraps=window.executor.router); window.executor.router = router
    thread_ids = []
    service.client.summarize_text.side_effect = lambda *_a, **_k: (thread_ids.append(get_ident()), SUMMARY)[1]
    window.wake_toggle.blockSignals(True); window.wake_toggle.setChecked(True); window.wake_toggle.blockSignals(False)
    window._after_tts = Mock()
    window.input.setText("Summarize report.pdf in Documents"); window.execute_command()
    assert window._active_thread is not None
    window._start_wake_listener(); assert window._wake_thread is None
    wait_idle(window)
    assert thread_ids and all(t != get_ident() for t in thread_ids)
    router.route.assert_called_once_with("Summarize report.pdf in Documents")
    assert SUMMARY in window.result_panel.toPlainText()
    window._after_tts.assert_called_once_with(window._start_wake_listener)
    window._set_status(Status.WAKE_LISTENING)
    assert SUMMARY in window.result_panel.toPlainText()
    assert window.history.count() == 0
    window.repository.add.assert_not_called(); window.tts.speak.assert_not_called()
    window.close()


def test_long_summary_spoken_only_short_overview(fs):
    window, service = setup_window(fs)
    service.client.summarize_text.return_value = "Overview: " + "short " * 200 + "\nMain points: details"
    window.tts.enabled = True
    window._complete(service.execute(request()))
    spoken = window.tts.speak.call_args.args[0]
    assert len(spoken) <= service.limits.spoken_characters
    assert len(window.result_panel.toPlainText()) > len(spoken)
    window.close()


def test_selection_typed_button_and_voice(fs):
    for mode in ("typed", "button", "voice"):
        window, service = setup_window(fs, selection=True)
        window._complete(service.execute(request(root="all")))
        window._start_wake_listener(); assert window._wake_thread is None
        if mode == "typed": window.input.setText("2"); window.execute_command()
        elif mode == "button": window.pdf_choices.setCurrentRow(1); window.pdf_select_button.click()
        else:
            window._voice_selection_token = window._document_selection["token"]
            window._voice_phase = "transcribing"
            window._voice_result = TranscriptionResult(success=True, text="select two", model_used="fake")
            window._voice_thread_finished()
        wait_idle(window)
        assert window._document_selection is None and SUMMARY in window.result_panel.toPlainText()
        window.repository.add.assert_not_called(); window.close()


def test_expiry_stop_and_unrelated_cancel_selection(fs):
    for action in ("expiry", "stop", "unrelated"):
        window, service = setup_window(fs, selection=True)
        window._complete(service.execute(request(root="all")))
        token = window._document_selection["token"]
        if action == "expiry": window._selection_timer.timeout.emit()
        elif action == "stop": window.stop()
        else:
            window.input.setText("What time is it?"); window.execute_command(); wait_idle(window)
        assert window._document_selection is None
        assert service.execute(selection=(token, 1)).status == Status.FAILED
        window.close()


def test_stale_voice_selection_ignored(fs):
    window, service = setup_window(fs, selection=True)
    window._complete(service.execute(request(root="all")))
    old = window._document_selection["token"]
    window._complete(service.execute(request(root="all")))
    window._voice_selection_token = old
    window._voice_phase = "transcribing"
    window._voice_result = TranscriptionResult(success=True, text="one", model_used="fake")
    window._voice_thread_finished()
    service.client.summarize_text.assert_not_called()
    assert window._active_thread is None
    window.close()


def test_stale_signals_and_duplicate_workers(fs, monkeypatch):
    window, service = setup_window(fs)
    monkeypatch.setattr(QThread, "start", lambda *_: None)
    window.input.setText("Summarize report.pdf in Documents"); window.execute_command()
    first = window._active_worker
    window.execute_command(); assert window._active_worker is first
    result = service.execute(request())
    window.result_panel.setPlainText("Current result")
    first.progress.emit("Summarizing", "Chunk 1 of 2")
    assert window.status.text() == "Status: Summarizing"
    window._active_worker = CommandWorker(window.executor, "Help")
    first.progress.emit("Extracting PDF", "Page 1 of 2")
    first.finished.emit(result)
    assert window.status.text() == "Status: Summarizing"
    assert window.result_panel.toPlainText() == "Current result"
    window._active_thread = window._active_worker = None
    window.close()


def test_ui_responsive_stop_and_close_cancel(fs):
    window, service = setup_window(fs)
    entered = Event()
    def delayed(_system, _data, cancel, **kwargs):
        entered.set()
        cancel.wait(3)
        return SUMMARY
    service.client.summarize_text.side_effect = delayed
    window.input.setText("Summarize report.pdf in Documents"); window.execute_command()
    ticks = []
    timer = QTimer(); timer.timeout.connect(lambda: ticks.append(1)); timer.start(5)
    deadline = monotonic() + 3
    while not entered.is_set() and monotonic() < deadline: _app().processEvents(); sleep(.001)
    assert entered.is_set()
    for _ in range(20): _app().processEvents(); sleep(.002)
    assert ticks
    window.stop(); wait_idle(window)
    assert "Cancelled" in window.status.text() and SUMMARY not in window.result_panel.toPlainText()
    timer.stop(); window.close()


def test_close_during_document_task(fs):
    window, service = setup_window(fs)
    entered = Event()
    def delayed(_system, _data, cancel, **kwargs):
        entered.set(); cancel.wait(3); return SUMMARY
    service.client.summarize_text.side_effect = delayed
    window.input.setText("Summarize report.pdf in Documents"); window.execute_command()
    deadline = monotonic() + 3
    while not entered.is_set() and monotonic() < deadline: _app().processEvents(); sleep(.001)
    window.close(); wait_idle(window)
    assert window._close_pending
    assert SUMMARY not in window.result_panel.toPlainText()
    window.close()


def test_real_wake_signals_keep_completed_pdf_summary(ui, fs):
    window, router = ui
    write_pdf(fs[1] / "report.pdf")
    service = service_for(fs)
    window.executor = CommandExecutor(documents=service)
    window._after_tts = Mock()
    window.wake_toggle.setChecked(True)
    wake_worker, wake_thread = window._wake_worker, window._wake_thread
    wake_worker.activation.emit("Hello")
    wake_thread.finished.emit()
    window._after_tts.call_args.args[0]()
    finish_recording(window)
    finish_transcription(window, "Summarize report.pdf in Documents")
    worker, thread = window._active_worker, window._active_thread
    worker.run(); thread.finished.emit()
    assert SUMMARY in window.result_panel.toPlainText()
    window._after_tts.call_args.args[0]()
    assert window.status.text() == "Status: Wake-word listening"
    assert window._wake_worker is not None and window._wake_worker is not wake_worker
    window._wake_worker.state_changed.emit("Listening")
    assert SUMMARY in window.result_panel.toPlainText()
    router.route.assert_called_once_with("Summarize report.pdf in Documents")
    window.repository.add.assert_not_called()


def test_immediate_stop_before_document_worker_starts(fs, monkeypatch):
    window, service = setup_window(fs)
    monkeypatch.setattr(QThread, "start", lambda *_: None)
    window.input.setText("Summarize report.pdf in Documents"); window.execute_command()
    worker, thread = window._active_worker, window._active_thread
    window.stop()
    assert window.status.text() == "Status: Cancelled"
    assert window.result_panel.toPlainText() == "Document task cancelled."
    worker.run(); thread.finished.emit()
    service.client.summarize_text.assert_not_called()
    window.close()
