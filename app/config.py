from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAKE_PHRASE = "Hello"


def load_project_env(path: Path | None = None) -> None:
    """Load the project environment while preserving process overrides."""
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=path or PROJECT_ROOT / ".env", override=False, encoding="utf-8-sig")


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _whisper_device() -> str:
    """Use CUDA only by explicit request; never let an `auto` probe reach Whisper."""
    return "cuda" if os.getenv("WHISPER_DEVICE", "cpu").strip().lower() == "cuda" else "cpu"


def _whisper_beam_size() -> int:
    configured = os.getenv("WHISPER_BEAM_SIZE")
    if configured is not None:
        return int(configured)
    return 5 if os.getenv("WHISPER_DEVICE", "auto").lower() == "cuda" else 1


def _transcription_timeout() -> float:
    configured = os.getenv("VOXPILOT_TRANSCRIPTION_TIMEOUT")
    if configured is not None:
        return float(configured)
    return 60.0 if os.getenv("WHISPER_DEVICE", "auto").lower() == "cuda" else 180.0


@dataclass(frozen=True)
class Settings:
    app_name: str = "VoxPilot AI"
    assistant_name: str = "Shyam"
    speech_enabled: bool = field(default_factory=lambda: _bool_env("VOXPILOT_SPEECH_ENABLED", True))
    database_path: Path = field(default_factory=lambda: user_data_path("VoxPilot AI", ensure_exists=True) / "history.sqlite3")
    ollama_base_url: str = field(default_factory=lambda: os.getenv("VOXPILOT_OLLAMA_BASE_URL", "http://localhost:11434"))
    primary_model: str = field(default_factory=lambda: os.getenv("VOXPILOT_PRIMARY_MODEL", "llama3.2:3b"))
    intent_model: str = field(default_factory=lambda: os.getenv("VOXPILOT_INTENT_MODEL", "llama3.2:3b"))
    intent_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_INTENT_TIMEOUT", "8")))
    intent_min_confidence: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_INTENT_MIN_CONFIDENCE", "0.85")))
    fallback_model: str = field(default_factory=lambda: os.getenv("VOXPILOT_FALLBACK_MODEL", "llama3.2:3b"))
    tool_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_TOOL_TIMEOUT", "10")))
    log_level: str = field(default_factory=lambda: os.getenv("VOXPILOT_LOG_LEVEL", "INFO"))
    whisper_model_size: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL_SIZE", "base.en"))
    whisper_device: str = field(default_factory=_whisper_device)
    whisper_compute_type: str = field(default_factory=lambda: os.getenv("WHISPER_COMPUTE_TYPE", "int8"))
    whisper_language: str = field(default_factory=lambda: os.getenv("WHISPER_LANGUAGE", "en"))
    whisper_beam_size: int = field(default_factory=_whisper_beam_size)
    sample_rate: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_SAMPLE_RATE", "16000")))
    max_recording_seconds: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_MAX_RECORDING_SECONDS", "15")))
    initial_wait_seconds: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_INITIAL_WAIT_SECONDS", "5")))
    silence_seconds: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_SILENCE_SECONDS", "1.5")))
    calibration_seconds: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_CALIBRATION_SECONDS", "0.7")))
    microphone_sensitivity: str = field(default_factory=lambda: os.getenv("VOXPILOT_MICROPHONE_SENSITIVITY", "normal").lower())
    min_speech_seconds: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_MIN_SPEECH_SECONDS", "0.4")))
    pre_speech_padding: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_PRE_SPEECH_PADDING", "0.25")))
    post_speech_padding: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_POST_SPEECH_PADDING", "0.4")))
    transcription_timeout: float = field(default_factory=_transcription_timeout)
    min_language_probability: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_MIN_LANGUAGE_PROBABILITY", "0.5")))
    save_audio: bool = field(default_factory=lambda: _bool_env("VOXPILOT_SAVE_AUDIO", False))
    voice_settings_path: Path = field(default_factory=lambda: user_data_path("VoxPilot AI", ensure_exists=True) / "voice-settings.json")
    recordings_path: Path = field(default_factory=lambda: user_data_path("VoxPilot AI", ensure_exists=True) / "recordings")
    wake_word_cooldown: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_WAKE_WORD_COOLDOWN", "1.5")))
    wake_window_seconds: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_WAKE_WINDOW_SECONDS", "3.0")))
