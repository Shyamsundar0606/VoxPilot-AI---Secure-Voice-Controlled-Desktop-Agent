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
    WAKE_LISTENING = "Wake-word listening"
    WAKE_DETECTED = "Wake detected"
    COMMAND_LISTENING = "Command listening"


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
    store_history: bool = True
    original_command: str
    normalized_command: str
    selected_tool: str | None
    status: Status
    result_message: str
    error_message: str | None = None
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AudioDevice(BaseModel):
    identifier: int
    name: str
    host_api_name: str = "Unknown"
    max_input_channels: int = 0
    default_sample_rate: float = 0.0
    supports_16000: bool = False
    supports_default_rate: bool = False
    usable: bool = False
    reason: str | None = None
    is_default: bool = False


class ResolvedAudioDevice(BaseModel):
    identifier: int
    name: str
    host_api_name: str
    sample_rate: int
    requires_resampling: bool = False


class RecordingResult(BaseModel):
    success: bool
    audio: Any | None = Field(default=None, exclude=True)
    sample_rate: int = 16000
    duration: float = 0.0
    original_duration: float = 0.0
    speech_duration: float = 0.0
    cancelled: bool = False
    error_code: str | None = None
    message: str = ""

    model_config = {"arbitrary_types_allowed": True}


class TranscriptionResult(BaseModel):
    success: bool
    text: str = ""
    language: str | None = None
    language_probability: float | None = None
    duration: float = 0.0
    processing_time: float = 0.0
    model_used: str
    cancelled: bool = False
    error_code: str | None = None
    message: str = ""


class WakeWordResult(BaseModel):
    detected: bool = False
    cancelled: bool = False
    error_code: str | None = None
    message: str = ""
    processing_time: float = 0.0
