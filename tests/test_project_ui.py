from unittest.mock import Mock
from threading import Event
from PySide6.QtCore import QTimer
from app.agent.executor import CommandExecutor
from app.models import Status
from app.projects.service import outcome
from app.ui.workers import CommandWorker, CommandSignalRelay
from tests.test_runtime import _window, _app, _wait_for_worker
from tests.test_projects import project_env, request
from tests.test_ui_voice_signals import ui, finish_recording, finish_transcription


def wait_closed(window):
    from time import monotonic, sleep
    deadline = monotonic() + 3
    while monotonic() < deadline and (window.isVisible() or window._active_thread is not None):
        _app().processEvents()
        sleep(.005)  # Release the GIL so the Python worker can finish cancellation.
    assert window._active_thread is None and not window.isVisible()


def test_ui_exact_plan_yes_and_history_exclusion(project_env):
    service, *_ = project_env
    window = _window(executor=CommandExecutor(projects=service))
    window.input.setText("Start project VoxPilot"); window.execute_command(); _wait_for_worker(window)
    assert window._confirmation["kind"] == "project"
    assert "Executable:" in window.confirmation_label.text()
    assert "Working directory:" in window.confirmation_label.text()
    service.processes.start.assert_not_called()
    window.input.setText("Yes"); window.execute_command(); _wait_for_worker(window)
    service.processes.start.assert_called_once()
    window.repository.add.assert_not_called()
    assert window.history.count() == 0
    window.close()


def test_no_and_expiry_do_not_route(project_env):
    service, *_ = project_env
    executor = CommandExecutor(projects=service)
    window = _window(executor=executor)
    window._complete(service.execute(request("start_project", project="VoxPilot")))
    executor.router = Mock()
    window.input.setText("No"); window.execute_command()
    assert window._confirmation is None
    window.input.setText("Yes"); window.execute_command()
    executor.router.route.assert_not_called(); service.processes.start.assert_not_called()
    window._complete(service.execute(request("start_project", project="VoxPilot")))
    window._confirmation_timer.timeout.emit()
    assert window._confirmation is None
    service.processes.start.assert_not_called(); window.close()


def test_stale_cancelled_worker_source_guard(project_env):
    service, *_ = project_env
    window = _window(executor=CommandExecutor(projects=service))
    old, current = CommandWorker(window.executor, "List my projects"), CommandWorker(window.executor, "List my projects")
    relay = CommandSignalRelay(window, old)
    old.finished.connect(relay.complete)
    window._active_worker = current
    window.result_panel.setPlainText("previous result")
    old.finished.emit(outcome("stale project data"))
    assert window.result_panel.toPlainText() == "previous result"
    window._active_worker = old; window._cancelled = True
    old.finished.emit(outcome("cancelled project data"))
    assert window.result_panel.toPlainText() == "previous result"
    window._cancelled = False; old.source = "command"
    old.finished.emit(outcome("wrong source"))
    assert window.result_panel.toPlainText() == "previous result"
    window._active_worker = None; window.close()


def test_project_confirmation_pauses_wake_and_cancel_resumes(project_env):
    service, *_ = project_env
    window = _window(executor=CommandExecutor(projects=service))
    window.wake_toggle.blockSignals(True); window.wake_toggle.setChecked(True); window.wake_toggle.blockSignals(False)
    window._complete(service.execute(request("start_project", project="VoxPilot")))
    window._start_wake_listener()
    assert window._wake_worker is None
    window._after_tts = Mock()
    window._cancel_confirmation("Project cancelled.")
    window._after_tts.assert_called_once()
    window.close()


def test_results_and_separate_bounded_output(project_env):
    service, *_ = project_env
    window = _window(executor=CommandExecutor(projects=service))
    result = service.execute(request("list_projects"))
    window._complete(result)
    assert window.project_selector.count() == 1
    prior = window.result_panel.toPlainText()
    window._set_status(Status.WAKE_LISTENING)
    assert window.result_panel.toPlainText() == prior
    window._complete(outcome("Running projects", project_data={"running": [{"name": "VoxPilot", "state": "running", "output": "output only"}]}))
    assert "output only" in window.project_output.toPlainText()
    assert "output only" not in window.result_panel.toPlainText()
    window.close()


def test_stop_and_close_cancel_without_killing_project(project_env):
    service, *_ = project_env
    window = _window(executor=CommandExecutor(projects=service))
    window._complete(service.execute(request("start_project", project="VoxPilot")))
    window.stop()
    assert window._confirmation is None
    service.processes.stop.assert_not_called()
    window.close()
    service.processes.close.assert_called_once()


def test_safe_window_startup_and_event_loop(project_env):
    service, *_ = project_env
    window = _window(executor=CommandExecutor(projects=service))
    window.show()
    QTimer.singleShot(20, window.close)
    wait_closed(window)
    assert not window.isVisible()
    assert window._active_thread is None and window._voice_thread is None and window._wake_thread is None


def test_discovery_worker_keeps_ui_responsive_and_closes(project_env):
    service, *_ = project_env
    entered = Event()
    def slow_discovery(cancel, root="all"):
        entered.set(); cancel.wait(1)
        return []
    service.discover = slow_discovery
    window = _window(executor=CommandExecutor(projects=service)); window.show()
    window.input.setText("List my projects"); window.execute_command()
    ticked = []
    QTimer.singleShot(20, lambda: (ticked.append(True), window.close()))
    wait_closed(window)
    assert ticked and entered.is_set()
    assert window._active_thread is None and not window.isVisible()
    service.processes.stop.assert_not_called()


def test_output_retention_timer(project_env):
    service, *_ = project_env
    window = _window(executor=CommandExecutor(projects=service))
    window._complete(outcome("Running projects", project_data={"running": [{"name": "VoxPilot", "state": "completed", "output": "temporary"}]}))
    window._project_output_timer.timeout.emit()
    assert window.project_output.toPlainText() == ""
    assert window.result_panel.toPlainText() == "Running projects"
    window.close()


def test_real_application_entry_point_smoke():
    import subprocess
    import sys
    completed = subprocess.run([sys.executable, "-m", "tests.project_startup_smoke"], shell=False,
        capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert "STARTUP_SMOKE_OK" in completed.stdout


def test_manual_voice_confirmation_uses_project_source(ui, project_env):
    window, router = ui
    service, *_ = project_env
    window.executor = CommandExecutor(projects=service)
    window._complete(service.execute(request("start_project", project="VoxPilot")))
    window.start_voice_command(); finish_recording(window)
    window._launch_command_worker = Mock()
    finish_transcription(window, "Yes")
    router.route.assert_not_called()
    worker = window._launch_command_worker.call_args.args[0]
    assert worker.source == "project" and worker.project_confirmation
    worker.run(); service.processes.start.assert_called_once()


def test_yes_without_confirmation_never_routes(ui):
    window, router = ui
    window.start_voice_command(); finish_recording(window); finish_transcription(window, "Yes")
    router.route.assert_not_called()
