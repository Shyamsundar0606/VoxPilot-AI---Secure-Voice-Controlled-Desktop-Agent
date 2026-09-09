import json
from threading import Event
from unittest.mock import Mock

import pytest

from app.agent.executor import CommandExecutor
from app.agent.intent_planner import IntentPlanner
from app.agent.ollama_client import OllamaError
from app.agent.router import CommandRouter
from app.models import ToolResult


def output(intent="open_application", arguments=None, **changes):
    value = dict(intent=intent, arguments={"application": "spotify"} if arguments is None else arguments,
                 confidence=0.94, requires_confirmation=False)
    value.update(changes)
    return json.dumps(value)


@pytest.mark.parametrize("text,intent,args,tool", [
    ("Could you bring up Spotify please?", "open_application", {"application": "spotify"}, "open_application"),
    ("Launch my browser please", "open_application", {"application": "chrome"}, "open_application"),
    ("Can you check the time?", "get_time", {}, "current_time"),
    ("What date are we on?", "get_date", {}, "current_date"),
    ("How much battery remains?", "battery_status", {}, "battery_status"),
    ("How much free disk space remains?", "storage_status", {}, "storage_status"),
    ("Please bring up Google", "open_safe_url", {"url_name": "google"}, "open_url"),
    ("Could I have some help?", "help", {}, "help"),
])
def test_natural_intents(text, intent, args, tool):
    client = Mock(complete=Mock(return_value=output(intent, args)))
    plan = IntentPlanner(client).plan(text)
    assert plan.request.tool_name == tool
    assert plan.request.arguments == args


def test_deterministic_first_and_independent_of_ollama():
    planner = Mock()
    registry = Mock(execute=Mock(return_value=ToolResult(success=True, message="opened")))
    executor = CommandExecutor(registry=registry, planner=planner)
    assert executor.execute("Open Spotify").selected_tool == "open_application"
    planner.plan.assert_not_called()
    registry.execute.assert_called_once()


def test_router_runs_before_model_and_history_uses_canonical_action():
    events = []
    router = Mock(wraps=CommandRouter())
    router.route.side_effect = lambda text: events.append("route") or CommandRouter().route(text)
    client = Mock()
    client.complete.side_effect = lambda *_: events.append("model") or output()
    registry = Mock(execute=Mock(return_value=ToolResult(success=True, message="opened")))
    result = CommandExecutor(router, registry, IntentPlanner(client)).execute("Could you open Spotify please?")
    assert events == ["route", "model"]
    assert result.original_command == "open_application spotify"
    registry.execute.assert_called_once()


@pytest.mark.parametrize("changes", [{"confidence": 0.2}, {"requires_confirmation": True}])
def test_low_confidence_and_confirmation_fail_closed(changes):
    assert IntentPlanner(Mock(complete=Mock(return_value=output(**changes)))).plan("open Spotify please").request is None


@pytest.mark.parametrize("message", ["Local Ollama request timed out.", "Ollama is unavailable."])
def test_transport_failures_recover(message):
    client = Mock(complete=Mock(side_effect=OllamaError(message)))
    plan = IntentPlanner(client).plan("Please open Spotify")
    assert plan.request is None and plan.message == message


def test_cancel_after_model_prevents_execution():
    cancel = Event()
    client = Mock()
    def complete(*_):
        cancel.set()
        return output()
    client.complete.side_effect = complete
    registry = Mock()
    result = CommandExecutor(registry=registry, planner=IntentPlanner(client)).execute("Please open Spotify", cancel)
    registry.execute.assert_not_called()
    assert "cancelled" in result.result_message.lower()


def test_wake_phrase_never_reaches_router_model_or_history():
    router, planner, registry = Mock(), Mock(), Mock()
    result = CommandExecutor(router, registry, planner).execute(" HELLO! ")
    router.route.assert_not_called(); planner.plan.assert_not_called(); registry.execute.assert_not_called()
    assert not result.store_history
