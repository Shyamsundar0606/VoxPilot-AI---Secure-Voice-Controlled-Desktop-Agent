import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.models import ExecutionResult, Status
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
    settings = SimpleNamespace(app_name="VoxPilot AI", assistant_name="Shyam")
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
