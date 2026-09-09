from threading import Event, get_ident
from time import monotonic, sleep
from unittest.mock import Mock

from app.agent.executor import CommandExecutor
from app.agent.intent_planner import IntentPlanner
from app.agent.ollama_client import OllamaError
from app.voice.voice_controller import VoiceCommandController
from app.models import TranscriptionResult
from tests.test_runtime import _window, _app


def test_stop_cancels_planning_outside_ui_thread():
    entered = Event()
    threads = []
    class Client:
        def complete(self, text, cancel):
            threads.append(get_ident())
            entered.set()
            cancel.wait(2)
            raise OllamaError("Intent request cancelled.")
    registry = Mock()
    window = _window(executor=CommandExecutor(registry=registry, planner=IntentPlanner(Client())))
    window.input.setText("Could you open Spotify please?")
    window.execute_command()
    try:
        deadline = monotonic() + 2
        while not entered.is_set() and monotonic() < deadline:
            _app().processEvents(); sleep(0.001)
        assert entered.is_set()
        assert threads == [threads[0]] and threads[0] != get_ident()
        # GUI event processing and Stop remain available during the model call.
        assert window.stop_button.isEnabled()
        window.stop()
        deadline = monotonic() + 2
        while window._active_thread is not None and monotonic() < deadline:
            _app().processEvents(); sleep(0.001)
        assert window._active_thread is None
        registry.execute.assert_not_called()
        window.repository.add.assert_not_called()
    finally:
        window.close()


def test_voice_preparation_does_not_call_model_on_ui_thread():
    router, executor = Mock(), Mock()
    controller = VoiceCommandController(router, executor, allow_intent_planning=True)
    result = TranscriptionResult(success=True, text="Could you open Spotify?", model_used="fake")
    assert controller.approved_command(result) == (result.text, None)
    router.route.assert_not_called(); executor.execute.assert_not_called()
