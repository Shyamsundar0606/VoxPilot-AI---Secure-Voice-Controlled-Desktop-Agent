from __future__ import annotations

import webbrowser
from collections.abc import Callable

from app.models import ToolResult
from app.security.policy import ALLOWED_URLS


class WebTools:
    def __init__(self, opener: Callable[[str], bool] = webbrowser.open):
        self.opener = opener

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
