from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.application_tools import ApplicationTools, ApprovedApplicationResolver


def resolver_for(*, which=None, registry=None, environment=None, existing=()):
    existing_paths = {str(Path(path)) for path in existing}
    return ApprovedApplicationResolver(
        which=which or (lambda _name: None),
        registry_lookup=registry or (lambda _name: None),
        environment=environment or {},
        is_file=lambda path: str(path) in existing_paths,
    )


def test_chrome_discovered_through_path():
    path = r"C:\Tools\Chrome\chrome.exe"
    resolver = resolver_for(which=lambda name: path if name == "chrome.exe" else None, existing=(path,))
    assert resolver.resolve("chrome") == [path]


def test_chrome_discovered_in_program_files():
    root = r"C:\Program Files"
    path = str(Path(root) / r"Google\Chrome\Application\chrome.exe")
    resolver = resolver_for(environment={"ProgramFiles": root}, existing=(path,))
    assert resolver.resolve("chrome") == [path]


def test_chrome_discovered_in_local_appdata():
    root = r"C:\Users\Shyam\AppData\Local"
    path = str(Path(root) / r"Google\Chrome\Application\chrome.exe")
    resolver = resolver_for(environment={"LOCALAPPDATA": root}, existing=(path,))
    assert resolver.resolve("chrome") == [path]


def test_chrome_discovered_through_app_paths_registry():
    path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    resolver = resolver_for(registry=lambda name: path if name == "chrome.exe" else None, existing=(path,))
    assert resolver.resolve("chrome") == [path]


def test_vscode_discovery():
    root = r"C:\Users\Shyam\AppData\Local"
    path = str(Path(root) / r"Programs\Microsoft VS Code\Code.exe")
    resolver = resolver_for(environment={"LOCALAPPDATA": root}, existing=(path,))
    assert resolver.resolve("vscode") == [path]


def test_word_discovery_from_registry():
    path = r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE"
    resolver = resolver_for(registry=lambda name: path if name == "WINWORD.EXE" else None, existing=(path,))
    assert resolver.resolve("word") == [path]


def test_spotify_discovery_from_appdata():
    root = r"C:\Users\Shyam\AppData\Roaming"
    path = str(Path(root) / r"Spotify\Spotify.exe")
    resolver = resolver_for(environment={"APPDATA": root}, existing=(path,))
    assert resolver.resolve("spotify") == [path]


def test_missing_application_returns_structured_failure():
    result = ApplicationTools(resolver=resolver_for()).open_application("chrome")
    assert not result.success
    assert result.error == "Application not found"


@pytest.mark.parametrize("application", ["photoshop", r"C:\Windows\System32\cmd.exe", "../evil.exe"])
def test_unknown_name_or_supplied_path_is_rejected(application):
    calls = []
    result = ApplicationTools(launcher=lambda *args, **kwargs: calls.append((args, kwargs)), resolver=resolver_for()).open_application(application)
    assert not result.success
    assert result.error == "Application not allowlisted"
    assert calls == []


def test_resolver_never_searches_filesystem_recursively():
    with patch.object(Path, "rglob", side_effect=AssertionError("recursive search attempted")), patch("os.walk", side_effect=AssertionError("filesystem walk attempted")):
        assert resolver_for().resolve("chrome") is None


def test_subprocess_receives_list_and_shell_is_false():
    path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    calls = []
    resolver = resolver_for(which=lambda name: path if name == "chrome.exe" else None, existing=(path,))
    result = ApplicationTools(launcher=lambda command, **kwargs: calls.append((command, kwargs)), resolver=resolver).open_application("chrome")
    assert result.success
    assert isinstance(calls[0][0], list)
    assert calls[0][0] == [path]
    assert calls[0][1]["shell"] is False


def test_spotify_uses_approved_uri_fallback_with_validated_explorer():
    explorer = r"C:\Windows\explorer.exe"
    resolver = resolver_for(
        which=lambda name: explorer if name == "explorer.exe" else None,
        existing=(explorer,),
    )
    assert resolver.resolve("spotify") == [explorer, "spotify:"]
