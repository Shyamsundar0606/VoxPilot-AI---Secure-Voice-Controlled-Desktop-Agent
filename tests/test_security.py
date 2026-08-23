import pytest

from app.models import ToolRequest
from app.security.validators import PolicyViolation, validate_tool_request


def test_unknown_tool_rejected():
    with pytest.raises(PolicyViolation):
        validate_tool_request(ToolRequest(tool_name="powershell", arguments={"command": "whoami"}))


@pytest.mark.parametrize("application", ["photoshop", "C:\\Windows\\System32\\cmd.exe", "../evil.exe"])
def test_application_allowlist_rejects_names_and_paths(application):
    with pytest.raises(PolicyViolation):
        validate_tool_request(ToolRequest(tool_name="open_application", arguments={"application": application}))


def test_extra_arguments_rejected():
    with pytest.raises(PolicyViolation):
        validate_tool_request(ToolRequest(tool_name="current_time", arguments={"command": "calc.exe"}))

