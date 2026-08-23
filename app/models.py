from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Status(str, Enum):
    IDLE = "Idle"
    LISTENING = "Listening"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"


class CommandRequest(BaseModel):
    original_command: str = Field(min_length=1, max_length=500)


class ToolRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class RoutedCommand(BaseModel):
    original_command: str
    normalized_command: str
    supported: bool
    tool_request: ToolRequest | None = None
    response: str | None = None


class ToolResult(BaseModel):
    success: bool
    message: str
    error: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    original_command: str
    normalized_command: str
    selected_tool: str | None
    status: Status
    result_message: str
    error_message: str | None = None
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

