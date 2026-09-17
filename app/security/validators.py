from __future__ import annotations
import re
import unicodedata

from app.models import ToolRequest
from app.security.policy import ALLOWED_APPLICATIONS, ALLOWED_TOOLS, ALLOWED_URLS


class PolicyViolation(ValueError):
    pass


MAX_SEARCH_QUERY_LENGTH = 300


def validate_search_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise PolicyViolation("Google search requires a query of 1 to 300 characters.")
    if any(unicodedata.category(char).startswith("C") or char in "\u2028\u2029" for char in query):
        raise PolicyViolation("Search queries cannot contain control characters or line breaks.")
    if re.search(r"\b[a-z][a-z0-9+.-]*\s*:|//|www\.", query, re.I):
        raise PolicyViolation("Search queries cannot contain URLs or URI schemes.")
    return query.strip()


def validate_tool_request(request: ToolRequest) -> None:
    if request.tool_name not in ALLOWED_TOOLS:
        raise PolicyViolation("The requested tool is not approved.")
    from app.knowledge.policy import KNOWLEDGE_TOOLS, validate_arguments as validate_knowledge
    if request.tool_name in KNOWLEDGE_TOOLS:
        validate_knowledge(request.tool_name, request.arguments)
        return
    from app.projects.policy import PROJECT_TOOLS, validate_arguments
    if request.tool_name in PROJECT_TOOLS:
        validate_arguments(request.tool_name, request.arguments)
        return
    from app.documents.policy import DOCUMENT_TOOLS, PdfArgs
    if request.tool_name in DOCUMENT_TOOLS:
        PdfArgs.model_validate(request.arguments)
        return
    from app.security.filesystem_policy import FILESYSTEM_TOOLS, validate_file_arguments
    if request.tool_name in FILESYSTEM_TOOLS:
        validate_file_arguments(request.tool_name, request.arguments)
        return
    expected = {
        "open_application": {"application"},
        "open_url": {"url_name"},
        "search_google": {"query"},
    }.get(request.tool_name, set())
    if set(request.arguments) != expected:
        raise PolicyViolation("The tool arguments are invalid.")
    if request.tool_name == "search_google":
        validate_search_query(request.arguments["query"])
    if request.tool_name == "open_application" and request.arguments["application"] not in ALLOWED_APPLICATIONS:
        raise PolicyViolation("That application is not available in the approved application list.")
    if request.tool_name == "open_url" and request.arguments["url_name"] not in ALLOWED_URLS:
        raise PolicyViolation("That URL is not approved.")
