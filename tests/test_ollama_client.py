import json
from threading import Event
from unittest.mock import Mock

import pytest
import requests

import app.agent.ollama_client as module
from app.agent.ollama_client import OllamaClient, OllamaError, local_endpoint, _http_request
from tests.test_intent_planner import output


@pytest.mark.parametrize("url", ["https://localhost:11434", "http://example.org", "http://127.0.0.1.evil", "http://user@localhost", "http://localhost/path", "http://localhost?x=y"])
def test_only_loopback_endpoint_allowed(url):
    with pytest.raises(ValueError): local_endpoint(url)


def test_localhost_is_pinned_to_loopback_ip():
    assert local_endpoint("http://localhost:11434") == "http://127.0.0.1:11434/api/chat"


@pytest.mark.parametrize("name", ["gpt-oss:120b-cloud", "someone/model", ""])
def test_cloud_or_remote_model_names_rejected(name):
    with pytest.raises(ValueError): OllamaClient(primary_model=name)


def transport(monkeypatch, response=None):
    context = Mock()
    receiver, sender = Mock(), Mock()
    receiver.poll.return_value = response is not None
    receiver.recv.return_value = response
    context.Pipe.return_value = receiver, sender
    context.Process.return_value.pid = 1
    context.Process.return_value.is_alive.return_value = True
    monkeypatch.setattr(module, "get_context", lambda _: context)
    return context, receiver


def test_json_schema_sent_and_process_cleaned_up(monkeypatch):
    context, _ = transport(monkeypatch, (True, output()))
    assert OllamaClient().complete("Please open Spotify") == output()
    args = context.Process.call_args.kwargs["args"]
    payload = args[1]
    assert payload["model"] == "llama3.2:3b"
    assert payload["format"]["additionalProperties"] is False
    assert payload["stream"] is False
    context.Process.return_value.terminate.assert_called_once()
    context.Process.return_value.join.assert_called_once()


def test_cancel_during_transport_terminates_child(monkeypatch):
    context, receiver = transport(monkeypatch)
    cancel = Event()
    receiver.poll.side_effect = lambda _: cancel.set() or False
    with pytest.raises(OllamaError, match="cancelled"):
        OllamaClient().complete("Please open Spotify", cancel)
    context.Process.return_value.terminate.assert_called_once()


def test_wall_timeout_terminates_child(monkeypatch):
    context, _ = transport(monkeypatch)
    times = iter([0, 9])
    monkeypatch.setattr(module, "monotonic", lambda: next(times))
    with pytest.raises(OllamaError, match="timed out"):
        OllamaClient().complete("Please open Spotify")
    context.Process.return_value.terminate.assert_called_once()


def fake_response(**kwargs):
    response = Mock(status_code=200, **kwargs)
    manager = Mock()
    manager.__enter__ = Mock(return_value=response)
    manager.__exit__ = Mock(return_value=False)
    return manager


def session_setup(monkeypatch, metadata=None):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    show = fake_response(json=Mock(return_value=metadata or {"model_info": {"general.architecture": "llama"}}))
    chat = fake_response(iter_content=Mock(return_value=[json.dumps({"message": {"content": output()}}).encode()]))
    session.post.side_effect = [show, chat]
    return session


def test_http_disables_proxies_redirects_and_cloud(monkeypatch):
    session = session_setup(monkeypatch)
    pipe = Mock()
    _http_request(local_endpoint("http://localhost"), {"model": "llama3.2:3b"}, 8, pipe)
    assert session.trust_env is False
    assert all(call.kwargs["allow_redirects"] is False for call in session.post.call_args_list)
    pipe.send.assert_called_once_with((True, output()))


def test_remote_alias_rejected_before_prompt_sent(monkeypatch):
    session = session_setup(monkeypatch, {"remote_model": "remote", "remote_host": "https://ollama.com"})
    pipe = Mock()
    _http_request(local_endpoint("http://localhost"), {"model": "alias"}, 8, pipe)
    assert session.post.call_count == 1
    assert pipe.send.call_args.args[0][0] is False


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_http_unavailability_is_recoverable(monkeypatch, error):
    session = session_setup(monkeypatch)
    session.post.side_effect = error
    pipe = Mock()
    _http_request(local_endpoint("http://localhost"), {"model": "llama3.2:3b"}, 8, pipe)
    assert pipe.send.call_args.args[0][0] is False
    pipe.close.assert_called_once()
