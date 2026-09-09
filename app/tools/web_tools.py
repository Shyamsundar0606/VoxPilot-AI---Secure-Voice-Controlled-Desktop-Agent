from __future__ import annotations

import webbrowser
from urllib.parse import urlencode
from collections.abc import Callable

from app.models import ToolResult
from app.security.policy import ALLOWED_URLS
from app.security.validators import PolicyViolation, validate_search_query


class WebTools:
    def __init__(self, opener: Callable[[str], bool] = webbrowser.open):
        self.opener = opener

    def search_google(self, query: str) -> ToolResult:
        try:
            query = validate_search_query(query)
        except PolicyViolation as exc:
            return ToolResult(success=False, message=str(exc), error="Invalid search query")
        url = "https://www.google.com/search?" + urlencode({"q": query})
        try:
            if self.opener(url) is False:
                raise OSError("Browser rejected the request")
            return ToolResult(success=True, message=f"Searching Google for {query}.")
        except OSError:
            return ToolResult(success=False, message="Google search could not be opened.", error="Browser unavailable")

    def open_url(self, url_name: str) -> ToolResult:
        url = ALLOWED_URLS.get(url_name)
        if not url:
            return ToolResult(success=False, message="That URL is not approved.", error="URL not allowlisted")
        label = {"google": "Google", "chatgpt": "ChatGPT"}.get(url_name, "Website")
        try:
            opened = self.opener(url)
            if opened is False:
                raise OSError("Browser rejected the request")
            return ToolResult(success=True, message=f"{label} is now open.")
        except OSError as exc:
            return ToolResult(success=False, message=f"{label} could not be opened.", error=type(exc).__name__)
