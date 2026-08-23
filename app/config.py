from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "VoxPilot AI"
    assistant_name: str = "Shyam"
    speech_enabled: bool = field(default_factory=lambda: _bool_env("VOXPILOT_SPEECH_ENABLED", True))
    database_path: Path = field(default_factory=lambda: user_data_path("VoxPilot AI", ensure_exists=True) / "history.sqlite3")
    ollama_base_url: str = field(default_factory=lambda: os.getenv("VOXPILOT_OLLAMA_BASE_URL", "http://localhost:11434"))
    primary_model: str = field(default_factory=lambda: os.getenv("VOXPILOT_PRIMARY_MODEL", "qwen3:latest"))
    fallback_model: str = field(default_factory=lambda: os.getenv("VOXPILOT_FALLBACK_MODEL", "llama3.2:3b"))
    tool_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_TOOL_TIMEOUT", "10")))
    log_level: str = field(default_factory=lambda: os.getenv("VOXPILOT_LOG_LEVEL", "INFO"))

