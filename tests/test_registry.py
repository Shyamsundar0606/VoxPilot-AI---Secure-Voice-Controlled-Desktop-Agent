from unittest.mock import Mock

from app.models import ToolRequest
from app.tools.registry import ToolRegistry


def test_registry_returns_structured_result():
    system = Mock()
    system.current_time.return_value.success = True
    system.current_time.return_value.message = "ok"
    result = ToolRegistry(system=system).execute(ToolRequest(tool_name="current_time"))
    assert result.success


def test_registry_rejects_unknown_tool():
    result = ToolRegistry().execute(ToolRequest(tool_name="shell"))
    assert not result.success
    assert result.error == "Policy violation"


def test_tool_exception_becomes_structured_failure():
    system = Mock()
    system.current_time.side_effect = RuntimeError("tool broke")
    result = ToolRegistry(system=system).execute(ToolRequest(tool_name="current_time"))
    assert not result.success
    assert result.error == "RuntimeError"
