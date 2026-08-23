import pytest

from app.agent.router import CommandRouter, normalize_command


@pytest.mark.parametrize("raw, expected", [("  Open   CHROME!! ", "open chrome"), ("What's   up?", "what s up")])
def test_normalization(raw, expected):
    assert normalize_command(raw) == expected


@pytest.mark.parametrize("command, tool, arguments", [
    ("What time is it?", "current_time", {}), ("Tell me the time", "current_time", {}),
    ("What is today's date?", "current_date", {}), ("Open Chrome", "open_application", {"application": "chrome"}),
    ("Open ChatGPT", "open_url", {"url_name": "chatgpt"}), ("Open ChatGPT in Chrome", "open_url", {"url_name": "chatgpt"}),
    ("Open Spotify", "open_application", {"application": "spotify"}), ("Open Settings", "open_application", {"application": "settings"}),
    ("Open Windows Settings", "open_application", {"application": "settings"}), ("Open Notepad", "open_application", {"application": "notepad"}),
    ("Open Microsoft Word", "open_application", {"application": "word"}), ("Open Word", "open_application", {"application": "word"}),
    ("Open Calculator", "open_application", {"application": "calculator"}), ("Open VS Code", "open_application", {"application": "vscode"}),
    ("Open Visual Studio Code", "open_application", {"application": "vscode"}), ("Open File Explorer", "open_application", {"application": "file_explorer"}),
    ("Check battery percentage", "battery_status", {}), ("What is my battery percentage?", "battery_status", {}),
    ("Check available storage", "storage_status", {}), ("How much storage is available?", "storage_status", {}),
    ("Help", "help", {}), ("What can you do?", "help", {}),
])
def test_supported_commands(command, tool, arguments):
    routed = CommandRouter().route(command)
    assert routed.supported
    assert routed.tool_request.tool_name == tool
    assert routed.tool_request.arguments == arguments


@pytest.mark.parametrize("command", ["Open Photoshop", "Delete my files", "Format the drive", "Shut down the laptop", "Restart the laptop", "Run this PowerShell command", "Disable Windows Defender", "Install this application"])
def test_unsupported_and_dangerous_commands(command):
    routed = CommandRouter().route(command)
    assert not routed.supported
    assert routed.tool_request is None

