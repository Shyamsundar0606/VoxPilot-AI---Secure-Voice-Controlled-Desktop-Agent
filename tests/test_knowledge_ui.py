from threading import Event
from time import sleep, monotonic
from unittest.mock import Mock
from PySide6.QtCore import QTimer
from app.agent.executor import CommandExecutor
from app.models import Status
from app.ui.workers import CommandWorker, CommandSignalRelay
from app.knowledge.service import outcome
from tests.test_knowledge import knowledge, index
from tests.test_filesystem import fs
from tests.test_runtime import _window, _app, _wait_for_worker
from tests.test_ui_voice_signals import ui, finish_recording, finish_transcription


def test_ui_ask_plain_sources_short_tts_and_no_history(knowledge):
    service, docs, *_ = knowledge
    (docs / 'a.txt').write_text('Synthetic safe evidence.'); index(service)
    window = _window(executor=CommandExecutor(knowledge=service)); window.tts.enabled = True
    window.knowledge_panel.question.setText('What evidence?'); window.knowledge_panel.action('ask')
    _wait_for_worker(window, 5000)
    assert 'Supported synthetic fact' in window.knowledge_panel.answer.toPlainText()
    assert window.knowledge_panel.sources.count() == 1
    assert len(window.tts.speak.call_args.args[0]) < 200
    window.repository.add.assert_not_called()
    window._wake_state_changed('Wake-word listening')
    assert 'Supported synthetic fact' in window.knowledge_panel.answer.toPlainText()
    window.close()


def test_clear_confirmation_cancel_yes_and_wake_pause(knowledge):
    service, docs, *_ = knowledge
    (docs / 'a.txt').write_text('Synthetic safe evidence.'); index(service)
    window = _window(executor=CommandExecutor(knowledge=service))
    window.knowledge_panel.action('clear'); _wait_for_worker(window)
    assert window._confirmation['kind'] == 'knowledge'
    window._start_wake_listener(); assert window._wake_worker is None
    window.input.setText('No'); window.execute_command()
    assert window._confirmation is None
    window.knowledge_panel.action('clear'); _wait_for_worker(window)
    window.input.setText('Yes'); window.execute_command(); _wait_for_worker(window)
    assert window.knowledge_panel.count.text() == 'Indexed documents: 0'
    assert (docs / 'a.txt').exists()
    window.close()


def test_stale_worker_and_wrong_source_ignored():
    window = _window(executor=CommandExecutor())
    worker = CommandWorker(window.executor, 'Show indexed documents')
    relay = CommandSignalRelay(window, worker)
    result = outcome('stale', knowledge_data={'answer': 'stale', 'sources': []})
    window.knowledge_panel.answer.setPlainText('keep')
    relay.complete(result)
    assert window.knowledge_panel.answer.toPlainText() == 'keep'
    window._active_worker = worker; worker.source = 'command'; relay.complete(result)
    assert window.knowledge_panel.answer.toPlainText() == 'keep'
    worker.source = 'knowledge'; window._cancelled = True; relay.complete(result)
    assert window.knowledge_panel.answer.toPlainText() == 'keep'
    window._active_worker = None; window.close()


def test_responsive_cancel_duplicate_prevention_and_shutdown(knowledge):
    service, docs, embedder, _ = knowledge
    (docs / 'a.txt').write_text('Synthetic evidence.')
    entered = Event()
    def slow(text, cancel, timeout, **kwargs):
        entered.set()
        while not cancel.is_set(): sleep(.005)
        raise ValueError('cancelled')
    embedder.embed.side_effect = slow
    window = _window(executor=CommandExecutor(knowledge=service))
    window.input.setText('Index documents in Documents'); window.execute_command()
    original = window._active_worker
    window.knowledge_panel.action('index'); assert window._active_worker is original
    ticks = []; QTimer.singleShot(10, lambda: ticks.append(True))
    deadline = monotonic() + 3
    while not entered.is_set() and monotonic() < deadline: _app().processEvents(); sleep(.005)
    assert ticks and entered.is_set()
    window.knowledge_panel.cancel_work(); _wait_for_worker(window, 5000)
    assert window._active_thread is None
    assert 'cancelled' in window.knowledge_panel.progress.text().lower()
    window.close()


def test_close_cancels_active_knowledge_worker(knowledge):
    service, docs, embedder, _ = knowledge
    (docs / 'a.txt').write_text('Synthetic evidence.')
    entered = Event()
    def slow(text, cancel, timeout, **kwargs):
        entered.set()
        while not cancel.is_set(): sleep(.005)
        raise ValueError('cancelled')
    embedder.embed.side_effect = slow
    window = _window(executor=CommandExecutor(knowledge=service)); window.show()
    window.input.setText('Index documents in Documents'); window.execute_command()
    deadline = monotonic() + 3
    while not entered.is_set() and monotonic() < deadline: _app().processEvents(); sleep(.005)
    assert entered.is_set()
    window.close()
    deadline = monotonic() + 3
    while (window._active_thread or window.isVisible()) and monotonic() < deadline: _app().processEvents(); sleep(.005)
    assert window._active_thread is None and not window.isVisible()


def test_hello_question_voice_cycle_resumes_without_erasing_answer(ui, knowledge):
    window, router = ui
    service, docs, *_ = knowledge
    (docs / 'report.txt').write_text('Cloud governance evidence.'); index(service)
    window.executor = CommandExecutor(knowledge=service)
    window._after_tts = Mock()
    window.wake_toggle.setChecked(True)
    wake_worker, wake_thread = window._wake_worker, window._wake_thread
    wake_worker.activation.emit('Hello'); router.route.assert_not_called()
    window.tts.speak.assert_called_once_with('Yes, how can I help you?')
    wake_thread.finished.emit(); window._after_tts.call_args.args[0]()
    finish_recording(window)
    command = 'Ask my documents what the report says about cloud security'
    finish_transcription(window, command)
    worker, thread = window._active_worker, window._active_thread
    assert worker.source == 'knowledge' and window._wake_worker is None
    worker.run(); thread.finished.emit()
    assert 'Supported synthetic fact' in window.knowledge_panel.answer.toPlainText()
    window._after_tts.call_args.args[0]()
    assert window._wake_worker is not None
    window._wake_worker.state_changed.emit('Listening')
    assert 'Supported synthetic fact' in window.knowledge_panel.answer.toPlainText()
    router.route.assert_called_once_with(command)
    window.repository.add.assert_not_called()


def test_knowledge_cancel_keeps_wake_enabled_and_schedules_resume(knowledge):
    service, *_ = knowledge
    window = _window(executor=CommandExecutor(knowledge=service))
    window.wake_toggle.blockSignals(True); window.wake_toggle.setChecked(True); window.wake_toggle.blockSignals(False)
    window._after_tts = Mock()
    window._complete(outcome('cancelled', False).model_copy(update={'status': Status.CANCELLED}))
    window._command_finished()
    assert window.wake_toggle.isChecked()
    window._after_tts.assert_called_once()
    window.close()
