from __future__ import annotations

from time import perf_counter
from threading import Event

from app.agent.router import CommandRouter
from app.models import ExecutionResult, Status
from app.tools.registry import ToolRegistry
from app.security.validators import validate_tool_request
from app.voice.wake_word import is_wake_phrase


class CommandExecutor:
    def __init__(self, router=None, registry=None, planner=None):
        self.router = router or CommandRouter()
        self.registry = registry or ToolRegistry()
        self.planner = planner

    def execute(self, command: str, cancel_event=None) -> ExecutionResult:
        started = perf_counter()
        cancel = cancel_event or Event()
        if is_wake_phrase(command):
            return ExecutionResult(original_command="", normalized_command="", selected_tool=None,
                                   status=Status.IDLE, result_message="Wake phrase consumed.", store_history=False)
        routed = self.router.route(command)
        if cancel.is_set():
            return ExecutionResult(original_command="[Cancelled request]", normalized_command="", selected_tool=None,
                                   status=Status.FAILED, result_message="Command cancelled.", store_history=False)
        if not routed.supported or routed.tool_request is None:
            if self.planner is None:
                return self._result(routed, None, False, routed.response or "Unsupported command.", None, started)
            plan = self.planner.plan(command, cancel)
            # Never persist the free-form prompt, even on failure or low confidence.
            routed.original_command = routed.normalized_command = "[Natural-language request]"
            if plan.request is None:
                return self._result(routed, None, False, plan.message, None, started)
            routed.tool_request = plan.request
            routed.original_command = routed.normalized_command = " ".join(
                [plan.request.tool_name, *plan.request.arguments.values()])
        if cancel.is_set():
            return self._result(routed, None, False, "Command cancelled.", None, started)
        try:
            validate_tool_request(routed.tool_request)
        except ValueError:
            return self._result(routed, None, False, "The requested action is not approved.", None, started)
        tool_result = self.registry.execute(routed.tool_request)
        return self._result(routed, routed.tool_request.tool_name, tool_result.success, tool_result.message, tool_result.error, started)

    @staticmethod
    def _result(routed, tool, success, message, error, started):
        return ExecutionResult(original_command=routed.original_command, normalized_command=routed.normalized_command, selected_tool=tool, status=Status.COMPLETED if success else Status.FAILED, result_message=message, error_message=error, duration_ms=round((perf_counter() - started) * 1000))
