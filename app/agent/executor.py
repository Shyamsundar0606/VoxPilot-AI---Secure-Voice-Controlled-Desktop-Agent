from __future__ import annotations

from time import perf_counter
from threading import Event

from app.agent.router import CommandRouter
from app.models import ExecutionResult, Status
from app.tools.registry import ToolRegistry
from app.security.validators import validate_tool_request
from app.voice.wake_word import is_wake_phrase
from app.security.filesystem_policy import FILESYSTEM_TOOLS
from app.security.confirmations import Confirmations
from app.models import ToolRequest


class CommandExecutor:
    def __init__(self, router=None, registry=None, planner=None, confirmations=None, documents=None, projects=None, knowledge=None):
        self.router = router or CommandRouter()
        self.registry = registry or ToolRegistry()
        self.planner = planner
        self.confirmations = confirmations or Confirmations()
        self.documents = documents
        self.projects = projects
        self.knowledge = knowledge

    def execute(self, command: str, cancel_event=None, progress=lambda *_: None) -> ExecutionResult:
        started = perf_counter()
        cancel = cancel_event or Event()
        self.confirmations.cancel()  # A new request invalidates every prior proposal.
        if self.documents: self.documents.cancel_selection()
        if self.projects: self.projects.cancel()
        if self.knowledge: self.knowledge.cancel()
        if command.strip().casefold().rstrip(".!?") in {"cancel pdf summarization", "cancel document task"}:
            return ExecutionResult(original_command="", normalized_command="", selected_tool=None,
                                   status=Status.CANCELLED, result_message="Document task cancelled.", store_history=False)
        if is_wake_phrase(command):
            return ExecutionResult(original_command="", normalized_command="", selected_tool=None,
                                   status=Status.IDLE, result_message="Wake phrase consumed.", store_history=False)
        routed = self.router.route(command)
        from app.knowledge.policy import KNOWLEDGE_TOOLS
        knowledge_request = routed.tool_request is not None and routed.tool_request.tool_name in KNOWLEDGE_TOOLS
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
                [plan.request.tool_name, *(str(value) for value in plan.request.arguments.values())])
        if cancel.is_set():
            return self._result(routed, None, False, "Command cancelled.", None, started)
        try:
            validate_tool_request(routed.tool_request)
        except ValueError:
            if knowledge_request:
                from app.knowledge.service import outcome
                return outcome('Invalid knowledge request. Select one approved source root and use a bounded question or safe relative filename.', False)
            return self._result(routed, None, False, "The requested action is not approved.", None, started)
        if routed.tool_request.tool_name in KNOWLEDGE_TOOLS:
            from app.knowledge.service import outcome
            return self.knowledge.execute(routed.tool_request, cancel, progress) if self.knowledge else outcome('Local knowledge is not configured.', False)
        from app.documents.policy import DOCUMENT_TOOLS
        from app.projects.policy import PROJECT_TOOLS
        if routed.tool_request.tool_name in PROJECT_TOOLS:
            if self.projects: return self.projects.execute(routed.tool_request, cancel)
            from app.projects.service import outcome
            return outcome("Project management is not configured.", False)
        if routed.tool_request.tool_name in DOCUMENT_TOOLS:
            if self.documents:
                return self.documents.execute(routed.tool_request, cancel, progress)
            return ExecutionResult(original_command="[Local PDF request]", normalized_command="", selected_tool="summarize_pdf",
                                   status=Status.FAILED, result_message="PDF processing is not configured.", store_history=False)
        if routed.tool_request.tool_name in FILESYSTEM_TOOLS:
            tool_result = self.registry.execute(routed.tool_request, cancel)
            result = self._result(routed, routed.tool_request.tool_name, tool_result.success, tool_result.message, tool_result.error, started)
            result.store_history = False  # Do not persist directory listings or local paths.
            if tool_result.success and tool_result.data.get("proposal") and not cancel.is_set():
                token = self.confirmations.propose(routed.tool_request, tool_result.data["identity"])
                result.confirmation = {"token": token, "parent": tool_result.data["parent"],
                    "folder_name": tool_result.data["folder_name"], "timeout": self.confirmations.timeout}
            return result
        tool_result = self.registry.execute(routed.tool_request)
        return self._result(routed, routed.tool_request.tool_name, tool_result.success, tool_result.message, tool_result.error, started)

    def confirm(self, token, cancel_event=None):
        cancel = cancel_event or Event()
        pending = self.confirmations.take(token)
        message, success = "Confirmation expired or was cancelled. Request the folder again.", False
        if pending is not None and not cancel.is_set():
            request = ToolRequest.model_validate_json(pending.request_json)
            validate_tool_request(request)
            outcome = self.registry.filesystem.execute(request, cancel, expected=list(pending.identity))
            message, success = outcome.message, outcome.success
        return ExecutionResult(original_command="create_folder", normalized_command="create_folder", selected_tool="create_folder",
            status=Status.COMPLETED if success else Status.FAILED, result_message=message, store_history=False)

    @staticmethod
    def _result(routed, tool, success, message, error, started):
        from app.knowledge.policy import KNOWLEDGE_TOOLS
        private = routed.tool_request is not None and routed.tool_request.tool_name in KNOWLEDGE_TOOLS
        return ExecutionResult(original_command='[Local knowledge operation]' if private else routed.original_command, normalized_command='' if private else routed.normalized_command, selected_tool=tool, status=Status.COMPLETED if success else Status.FAILED, result_message=message, error_message=error, duration_ms=round((perf_counter() - started) * 1000), store_history=not private)
