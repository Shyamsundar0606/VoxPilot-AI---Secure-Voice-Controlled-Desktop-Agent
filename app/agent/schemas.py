"""Strict model-output schema; public intent names map to existing tools."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models import ToolRequest
from app.security.validators import validate_tool_request


class IntentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["open_application", "open_safe_url", "search_google", "get_time", "get_date", "battery_status", "storage_status", "help", "open_folder", "list_directory", "find_file", "create_folder", "file_info", "summarize_pdf", "locate_pdf"]
    arguments: dict[str, str | int]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    requires_confirmation: bool

    @model_validator(mode="after")
    def check_arguments(self):
        validate_tool_request(self.to_request())
        from app.security.policy import CONFIRMATION_REQUIRED_TOOLS
        if self.intent in CONFIRMATION_REQUIRED_TOOLS: self.requires_confirmation = True
        return self

    def to_request(self):
        name = {"open_safe_url": "open_url", "get_time": "current_time", "get_date": "current_date"}.get(self.intent, self.intent)
        return ToolRequest(tool_name=name, arguments=self.arguments)


def parse_intent(raw: str) -> IntentOutput:
    if not isinstance(raw, str) or len(raw) > 8192: raise ValueError("Invalid response size")
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError("Duplicate JSON field")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError("Nonfinite JSON number")
    return IntentOutput.model_validate(json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_constant))
