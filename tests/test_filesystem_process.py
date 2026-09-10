from threading import Event
from unittest.mock import Mock

from app.filesystem.service import FilesystemService
from app.models import ToolResult
from tests.test_filesystem import request


def setup(monkeypatch, response=None):
    import app.filesystem.service as module
    context, receiver, sender = Mock(), Mock(), Mock()
    context.Pipe.return_value = receiver, sender
    context.Process.return_value.pid = 1
    receiver.poll.return_value = response is not None
    receiver.recv.return_value = response
    monkeypatch.setattr(module, "get_context", lambda _: context)
    roots = Mock(configuration=Mock(return_value=({}, None)))
    return FilesystemService(roots), context, receiver


def test_process_result_and_cleanup(monkeypatch):
    service, context, _ = setup(monkeypatch, ToolResult(success=True, message="done").model_dump())
    assert service.execute(request("list_directory", root="documents", relative_path="")).success
    context.Process.return_value.join.assert_called_once()
    context.Process.return_value.close.assert_called_once()


def test_hard_timeout_terminates_process(monkeypatch):
    import app.filesystem.service as module
    service, context, _ = setup(monkeypatch)
    times = iter([0, 10])
    monkeypatch.setattr(module, "monotonic", lambda: next(times))
    assert "timed out" in service.execute(request("list_directory", root="documents", relative_path="")).message
    context.Process.return_value.terminate.assert_called_once()


def test_stop_terminates_process(monkeypatch):
    service, context, receiver = setup(monkeypatch)
    cancel = Event()
    receiver.poll.side_effect = lambda _: cancel.set() or False
    assert "cancelled" in service.execute(request("list_directory", root="documents", relative_path=""), cancel).message
    context.Process.return_value.terminate.assert_called_once()


def test_pre_cancelled_never_starts_child(monkeypatch):
    service, context, _ = setup(monkeypatch)
    cancel = Event(); cancel.set()
    service.execute(request("list_directory", root="documents", relative_path=""), cancel)
    context.Process.return_value.start.assert_not_called()
