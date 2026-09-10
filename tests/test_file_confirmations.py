from threading import Event
from unittest.mock import Mock
import json

import pytest

from app.agent.executor import CommandExecutor
from app.agent.router import CommandRouter
from app.agent.schemas import parse_intent
from app.agent.intent_planner import IntentPlanner
from app.models import Status
from app.security.confirmations import Confirmations
from app.tools.registry import ToolRegistry
from tests.test_filesystem import fs, request


def executor_for(service, confirmations=None):
    return CommandExecutor(registry=ToolRegistry(filesystem=service), confirmations=confirmations)


def propose(executor): return executor.execute("Create a folder called Internship Applications in Documents")


def test_creation_requires_one_shot_confirmation(fs):
    service, docs, _ = fs
    executor = executor_for(service)
    result = propose(executor)
    assert result.confirmation["parent"] == str(docs)
    assert result.confirmation["folder_name"] == "Internship Applications"
    assert not (docs / "Internship Applications").exists()
    token = result.confirmation["token"]
    assert executor.confirm(token).status == Status.COMPLETED
    assert (docs / "Internship Applications").is_dir()
    assert executor.confirm(token).status == Status.FAILED
    assert propose(executor).status == Status.FAILED


@pytest.mark.parametrize("action", ["cancel", "expired", "unrelated", "stop"])
def test_cancel_expiry_new_command_prevent_write(fs, action):
    service, docs, _ = fs
    time = [0]
    confirmations = Confirmations(timeout=10, clock=lambda: time[0])
    executor = executor_for(service, confirmations)
    token = propose(executor).confirmation["token"]
    cancel = Event()
    if action == "cancel": confirmations.cancel()
    elif action == "expired": time[0] = 10
    elif action == "unrelated": executor.execute("Hello")
    else: cancel.set()
    assert executor.confirm(token, cancel).status == Status.FAILED
    assert not (docs / "Internship Applications").exists()


def test_model_false_cannot_bypass_write_confirmation(fs):
    service, docs, _ = fs
    raw = json.dumps({"intent": "create_folder", "arguments": {"root": "documents", "relative_parent": "", "folder_name": "Applications"},
                      "confidence": 0.96, "requires_confirmation": False})
    assert parse_intent(raw).requires_confirmation is True
    client = Mock(complete=Mock(return_value=raw))
    executor = CommandExecutor(registry=ToolRegistry(filesystem=service), planner=IntentPlanner(client))
    result = executor.execute("Please make a folder Applications in documents")
    assert result.confirmation is not None
    assert not (docs / "Applications").exists()


def test_parent_identity_change_invalidates_confirmation(fs, monkeypatch):
    service, docs, _ = fs
    executor = executor_for(service)
    token = propose(executor).confirmation["token"]
    monkeypatch.setattr(service, "identity", lambda path: [str(path), 999, 999])
    assert executor.confirm(token).status == Status.FAILED
    assert not (docs / "Internship Applications").exists()


@pytest.mark.parametrize("text,tool", [
    ("Open my Documents folder", "open_folder"), ("Open Downloads", "open_folder"),
    ("Show files in Downloads", "list_directory"), ("List folders in Documents", "list_directory"),
    ("Find my resume in Documents", "find_file"), ("Find files named invoice", "find_file"),
    ("Create a folder called Internship Applications in Documents", "create_folder"),
    ("Show information about resume.pdf", "file_info"),
])
def test_deterministic_file_commands(text, tool):
    assert CommandRouter().route(text).tool_request.tool_name == tool


@pytest.mark.parametrize("args", [
    {"root": "C:\\Users", "relative_path": ""},
    {"root": "documents", "relative_path": "../outside"},
    {"root": "documents", "relative_path": "", "approved": True},
])
def test_model_file_schema_rejects_paths_and_extra_fields(args):
    with pytest.raises(ValueError):
        parse_intent(json.dumps({"intent": "open_folder", "arguments": args, "confidence": 0.98, "requires_confirmation": False}))


def test_registry_create_is_proposal_even_without_executor(fs):
    service, docs, _ = fs
    result = ToolRegistry(filesystem=service).execute(request("create_folder", root="documents", relative_parent="", folder_name="Safe"))
    assert result.data["proposal"]
    assert not (docs / "Safe").exists()
