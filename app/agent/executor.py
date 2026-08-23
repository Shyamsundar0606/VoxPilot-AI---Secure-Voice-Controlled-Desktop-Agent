from __future__ import annotations

from time import perf_counter

from app.agent.router import CommandRouter
from app.models import ExecutionResult, Status
from app.tools.registry import ToolRegistry


class CommandExecutor:
    def __init__(self, router=None, registry=None):
        self.router = router or CommandRouter()
        self.registry = registry or ToolRegistry()

    def execute(self, command: str) -> ExecutionResult:
        started = perf_counter()
        routed = self.router.route(command)
        if not routed.supported or routed.tool_request is None:
            return self._result(routed, None, False, routed.response or "Unsupported command.", None, started)
        tool_result = self.registry.execute(routed.tool_request)
        return self._result(routed, routed.tool_request.tool_name, tool_result.success, tool_result.message, tool_result.error, started)

    @staticmethod
    def _result(routed, tool, success, message, error, started):
        return ExecutionResult(original_command=routed.original_command, normalized_command=routed.normalized_command, selected_tool=tool, status=Status.COMPLETED if success else Status.FAILED, result_message=message, error_message=error, duration_ms=round((perf_counter() - started) * 1000))

