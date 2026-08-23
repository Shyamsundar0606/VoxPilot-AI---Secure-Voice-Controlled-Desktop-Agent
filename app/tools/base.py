from __future__ import annotations

from typing import Protocol

from app.models import ToolResult


class Tool(Protocol):
    def execute(self, **kwargs: object) -> ToolResult: ...

