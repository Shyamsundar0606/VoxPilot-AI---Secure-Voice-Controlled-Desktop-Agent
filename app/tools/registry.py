from __future__ import annotations

import logging

from app.models import ToolRequest, ToolResult
from app.security.validators import PolicyViolation, validate_tool_request
from app.tools.application_tools import ApplicationTools
from app.tools.system_tools import SystemTools
from app.tools.web_tools import WebTools


HELP_MESSAGE = "I can tell the time or date, check battery or storage, search Google, and open approved applications. I can open or list approved folders, find files by name, show file information, and propose creating a folder for your confirmation. I can locate and summarize text-based PDFs in Desktop, Documents, Downloads and approved project folders."
logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, system=None, applications=None, web=None, filesystem=None):
        self.system = system or SystemTools()
        self.applications = applications or ApplicationTools()
        self.web = web or WebTools()
        self.filesystem = filesystem

    def execute(self, request: ToolRequest, cancel_event=None) -> ToolResult:
        try:
            validate_tool_request(request)
        except ValueError:
            return ToolResult(success=False, message="The requested tool or arguments are not approved.", error="Policy violation")
        from app.security.filesystem_policy import FILESYSTEM_TOOLS
        from app.documents.policy import DOCUMENT_TOOLS
        if request.tool_name in DOCUMENT_TOOLS:
            return ToolResult(success=False, message="Use the configured document execution pipeline.")
        if request.tool_name in FILESYSTEM_TOOLS:
            if self.filesystem is None: return ToolResult(success=False, message="File operations are not configured.")
            # create_folder always prepares a proposal here, never writes.
            return self.filesystem.execute(request, cancel_event)
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
