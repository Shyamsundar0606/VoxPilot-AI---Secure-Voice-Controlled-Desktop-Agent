"""Dedicated summary payloads still use the existing local-only transport."""
from threading import Event
from unittest.mock import Mock
import json
import pytest

from app.agent.ollama_client import OllamaClient, OllamaError, _http_request
from app.documents.summarizer import SUMMARY_PROMPT
from tests.test_ollama_client import transport, session_setup, fake_response
from tests.test_documents import SUMMARY
import app.agent.ollama_client as module


def test_summary_payload_has_no_tool_schema_and_buffers_released(monkeypatch):
    client = OllamaClient()
    captured = []
    def complete(payload, cancel, timeout):
        captured.append(json.loads(json.dumps(payload)))
        assert timeout == 180
        return SUMMARY
    client._request = Mock(side_effect=complete)
    assert client.summarize_text(SUMMARY_PROMPT, "untrusted test data") == SUMMARY
    payload = captured[0]
    assert "tools" not in payload and "format" not in payload
    assert payload["messages"][0]["content"] == SUMMARY_PROMPT
    assert "open_application" not in json.dumps(payload)
    assert client._request.call_args.args[0]["messages"] == []


def test_summary_transport_local_and_plain_response(monkeypatch):
    session = session_setup(monkeypatch)
    show = fake_response(json=Mock(return_value={"model_info": {"general.architecture": "llama"}}))
    chat = fake_response(iter_content=Mock(return_value=[json.dumps({"message": {"content": SUMMARY}}).encode()]))
    session.post.side_effect = [show, chat]
    pipe = Mock()
    _http_request(OllamaClient().endpoint, {"model": "llama3.2:3b", "messages": []}, 180, pipe)
    pipe.send.assert_called_once_with((True, SUMMARY))
    assert session.trust_env is False
    assert all(call.args[0].startswith("http://127.0.0.1:") for call in session.post.call_args_list)
    assert all(call.kwargs["allow_redirects"] is False for call in session.post.call_args_list)


def test_summary_timeout_terminates_model_process(monkeypatch):
    context, _ = transport(monkeypatch)
    times = iter([0, 181])
    monkeypatch.setattr(module, "monotonic", lambda: next(times))
    with pytest.raises(OllamaError, match="timed out"):
        OllamaClient().summarize_text(SUMMARY_PROMPT, "data", timeout=180)
    context.Process.return_value.terminate.assert_called_once()


def test_summary_cancellation_terminates_model_process(monkeypatch):
    context, receiver = transport(monkeypatch)
    cancel = Event()
    receiver.poll.side_effect = lambda _: cancel.set() or False
    with pytest.raises(OllamaError, match="cancelled"):
        OllamaClient().summarize_text(SUMMARY_PROMPT, "data", cancel)
    context.Process.return_value.terminate.assert_called_once()


def test_summary_refuses_remote_alias_before_sending_document(monkeypatch):
    session = session_setup(monkeypatch, {"remote_host": "https://example.com", "remote_model": "test"})
    pipe = Mock()
    _http_request(OllamaClient().endpoint, {"model": "alias", "messages": [{"content": "synthetic document marker"}]}, 180, pipe)
    assert session.post.call_count == 1
    assert "synthetic document marker" not in str(session.post.call_args_list)
    assert pipe.send.call_args.args[0][0] is False
