from __future__ import annotations

from app.models import ToolRequest
from app.security.policy import ALLOWED_APPLICATIONS, ALLOWED_TOOLS, ALLOWED_URLS


class PolicyViolation(ValueError):
    pass


def validate_tool_request(request: ToolRequest) -> None:
    if request.tool_name not in ALLOWED_TOOLS:
        raise PolicyViolation("The requested tool is not approved.")
    expected = {
        "open_application": {"application"},
        "open_url": {"url_name"},
    }.get(request.tool_name, set())
    if set(request.arguments) != expected:
        raise PolicyViolation("The tool arguments are invalid.")
    if request.tool_name == "open_application" and request.arguments["application"] not in ALLOWED_APPLICATIONS:
        raise PolicyViolation("That application is not available in the approved application list.")
    if request.tool_name == "open_url" and request.arguments["url_name"] not in ALLOWED_URLS:
        raise PolicyViolation("That URL is not approved.")

