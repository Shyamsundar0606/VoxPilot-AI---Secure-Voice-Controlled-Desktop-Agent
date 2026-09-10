from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import Mock
import json

import pytest

from app.filesystem.roots import ApprovedRoots
from app.filesystem.service import FilesystemService
from app.models import ToolRequest
from app.security.filesystem_policy import safe_relative, safe_component


@pytest.fixture
def fs():
    # A temporary sandbox under the workspace avoids approving AppData (where
    # Windows normally places pytest's temp root). No user folder is used.
    with TemporaryDirectory(prefix="voxpilot-test-", dir=Path.cwd()) as directory:
        base = Path(directory)
        documents, downloads = base / "Documents", base / "Downloads"
        documents.mkdir(); downloads.mkdir()
        platform = Mock(fixed_drive=Mock(return_value=True))
        roots = ApprovedRoots(base / "settings.json", platform, {"documents": documents, "downloads": downloads})
        yield FilesystemService(roots, isolated=False, max_depth=1, max_results=3), documents, downloads


def request(tool, **args): return ToolRequest(tool_name=tool, arguments=args)


@pytest.mark.parametrize("root", ["documents", "downloads"])
def test_open_approved_folder(fs, root):
    service, docs, downloads = fs
    result = service.execute(request("open_folder", root=root, relative_path=""))
    assert result.success
    service.roots.platform.open_folder.assert_called_once_with(docs if root == "documents" else downloads)


def test_listing_filters_hidden_sensitive_and_kind(fs):
    service, docs, _ = fs
    (docs / "visible.txt").write_text("test")
    (docs / ".hidden").write_text("hidden")
    (docs / ".git").mkdir(); (docs / "venv").mkdir(); (docs / "Work").mkdir()
    result = service.execute(request("list_directory", root="documents", relative_path=""))
    assert result.success and set(result.data["entries"]) == {"visible.txt", "Work/"}
    folders = service.execute(request("list_directory", root="documents", relative_path="", kind="folders"))
    assert folders.data["entries"] == ["Work/"]


def test_listing_truncates(fs):
    service, docs, _ = fs
    for n in range(6): (docs / f"entry{n}").touch()
    result = service.execute(request("list_directory", root="documents", relative_path=""))
    assert len(result.data["entries"]) == 3 and result.data["truncated"]
    assert "truncated" in result.message


def test_search_depth_count_and_roots(fs):
    service, docs, downloads = fs
    (docs / "resume.pdf").touch()
    (docs / "one").mkdir(); (docs / "one" / "resume2.pdf").touch()
    (docs / "one" / "two").mkdir(); (docs / "one" / "two" / "resume3.pdf").touch()
    (downloads / "resume4.pdf").touch()
    result = service.execute(request("find_file", root="documents", query="resume", max_results=20))
    assert set(result.data["entries"]) == {"resume.pdf", "one/resume2.pdf"}
    assert result.data["truncated"]
    result = service.execute(request("find_file", root="all", query="resume", max_results=1))
    assert len(result.data["entries"]) == 1 and result.data["truncated"]


def test_file_info_does_not_read_contents(fs, monkeypatch):
    service, docs, _ = fs
    (docs / "resume.pdf").write_bytes(b"1234")
    monkeypatch.setattr(Path, "read_bytes", Mock(side_effect=AssertionError("No reading")))
    result = service.execute(request("file_info", root="documents", relative_path="resume.pdf"))
    assert result.success and result.data["size_bytes"] == 4


@pytest.mark.parametrize("path", ["../outside", "a/../b", "/absolute", "C:\\Windows", "C:relative", "\\\\host\\share", "\\\\?\\C:\\", "file:stream", "a\x00b", "a\nb", "AppData", ".ssh", ".git", ".venv", "venv", "ProgramData", "System32", "Program Files", "User Data", "a//b"])
def test_path_injections_rejected(fs, path):
    service, _, _ = fs
    with pytest.raises(ValueError): safe_relative(path)
    result = service.execute(request("open_folder", root="documents", relative_path=path))
    assert not result.success
    service.roots.platform.open_folder.assert_not_called()


@pytest.mark.parametrize("name", ["CON", "con.txt", "PRN", "AUX", "NUL", "COM1", "COM9.log", "LPT1", "name.", "name ", "..", "a/b", "a\\b", "a:b", "a\tname"])
def test_invalid_creation_names(fs, name):
    service, _, _ = fs
    with pytest.raises(ValueError): safe_component(name)
    assert not service.execute(request("create_folder", root="documents", relative_parent="", folder_name=name)).success


def test_link_or_junction_escape_rejected_without_following(fs, monkeypatch):
    service, docs, downloads = fs
    (docs / "redirect").mkdir(); (downloads / "secret.pdf").touch()
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == docs / "redirect" or original(path))
    assert not service.execute(request("open_folder", root="documents", relative_path="redirect")).success
    listing = service.execute(request("find_file", root="documents", query="secret"))
    assert listing.data["entries"] == []


def test_symlink_is_not_followed(fs, monkeypatch):
    service, docs, _ = fs
    (docs / "link").mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == docs / "link" or original(path))
    assert not service.execute(request("open_folder", root="documents", relative_path="link")).success


def test_project_roots_persist_but_sensitive_roots_rejected(fs):
    service, docs, downloads = fs
    project = downloads / "MyProject"; project.mkdir()
    key = service.roots.add_project(project)
    assert key == "project_1" and service.roots.resolve(key) == project
    assert json.loads(service.roots.settings_path.read_text())["project_roots"][key] == str(project)
    for path in [Path(docs.anchor), docs / "AppData", docs / ".ssh"]:
        with pytest.raises(ValueError): service.roots.add_project(path)
    service.roots.platform.fixed_drive.return_value = False
    with pytest.raises(ValueError): service.roots.add_project(project)


def test_errors_cancellation_timeout_are_recoverable(fs, monkeypatch):
    service, docs, _ = fs
    assert not service.execute(request("file_info", root="documents", relative_path="missing")).success
    cancel = Event(); cancel.set()
    assert "cancelled" in service.execute(request("list_directory", root="documents", relative_path=""), cancel).message
    ticks = iter([0, 10, 11])
    service.clock = lambda: next(ticks)
    assert "timed out" in service.execute(request("list_directory", root="documents", relative_path="")).message
    service.clock = __import__("time").monotonic
    monkeypatch.setattr(Path, "iterdir", Mock(side_effect=PermissionError()))
    assert not service.execute(request("list_directory", root="documents", relative_path="")).success


def test_root_and_final_path_are_rechecked(fs, monkeypatch):
    service, docs, _ = fs
    original = service.roots.resolve
    calls = []
    def resolve(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2: raise ValueError("Changed")
        return original(*args, **kwargs)
    monkeypatch.setattr(service.roots, "resolve", resolve)
    assert not service.execute(request("open_folder", root="documents", relative_path="")).success
    service.roots.platform.open_folder.assert_not_called()


def test_custom_named_virtual_environment_rejected(fs):
    service, docs, _ = fs
    environment = docs / "python-runtime"
    environment.mkdir(); (environment / "pyvenv.cfg").write_text("test")
    assert not service.execute(request("open_folder", root="documents", relative_path="python-runtime")).success
    with pytest.raises(ValueError): service.roots.add_project(environment)


def test_cancel_project_approval_does_not_persist(fs):
    service, _, downloads = fs
    cancel = Event(); cancel.set()
    with pytest.raises(ValueError): service.roots.add_project(downloads, cancel)
    assert not service.roots.settings_path.exists()
