from __future__ import annotations

import logging

from app.models import ToolRequest, ToolResult
from app.security.validators import PolicyViolation, validate_tool_request
from app.tools.application_tools import ApplicationTools
from app.tools.system_tools import SystemTools
from app.tools.web_tools import WebTools


HELP_MESSAGE = "I can tell the time or date, check battery or storage, search Google, and open Chrome, ChatGPT, Spotify, Settings, Notepad, Word, Calculator, VS Code, or File Explorer."
logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, system=None, applications=None, web=None):
        self.system = system or SystemTools()
        self.applications = applications or ApplicationTools()
        self.web = web or WebTools()

    def execute(self, request: ToolRequest) -> ToolResult:
        try:
            validate_tool_request(request)
        except PolicyViolation as exc:
            return ToolResult(success=False, message=str(exc), error="Policy violation")
        handlers = {
            "current_time": self.system.current_time,
            "current_date": self.system.current_date,
            "battery_status": self.system.battery_status,
            "storage_status": self.system.storage_status,
            "open_application": self.applications.open_application,
            "open_url": self.web.open_url,
            "search_google": self.web.search_google,
            "help": lambda: ToolResult(success=True, message=HELP_MESSAGE),
        }
        try:
            return handlers[request.tool_name](**request.arguments)
        except Exception as exc:
            logger.exception("Approved tool failed: %s", request.tool_name)
            return ToolResult(success=False, message="The approved action could not be completed.", error=type(exc).__name__)
