from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAKE_PHRASE = "Hello"


def configured_wake_phrase():
    return os.getenv("VOXPILOT_WAKE_PHRASE", WAKE_PHRASE).strip()


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
    project_discovery_depth: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PROJECT_DISCOVERY_DEPTH", "3")))
    project_discovery_limit: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PROJECT_DISCOVERY_LIMIT", "1000")))
    project_result_limit: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PROJECT_RESULT_LIMIT", "100")))
    project_discovery_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_PROJECT_DISCOVERY_TIMEOUT", "15")))
    project_output_max_lines: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PROJECT_OUTPUT_MAX_LINES", "500")))
    project_output_max_bytes: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PROJECT_OUTPUT_MAX_BYTES", "262144")))
    project_confirmation_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_PROJECT_CONFIRMATION_TIMEOUT", "30")))
    project_stop_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_PROJECT_STOP_TIMEOUT", "10")))
    project_output_retention: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_PROJECT_OUTPUT_RETENTION", "60")))
    project_profiles_path: Path = field(default_factory=lambda: user_data_path("VoxPilot AI", ensure_exists=True) / "project-profiles.json")
    wake_engine: str = field(default_factory=lambda: os.getenv("VOXPILOT_WAKE_ENGINE", "vosk").strip().lower())
    wake_phrase: str = field(default_factory=configured_wake_phrase)
    vosk_model_path: Path = field(default_factory=lambda: Path(os.getenv("VOSK_MODEL_PATH", "models/vosk-model-small-en-us-0.15")))
    vosk_sample_rate: int = field(default_factory=lambda: int(os.getenv("VOSK_SAMPLE_RATE", "16000")))
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
    filesystem_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_FILESYSTEM_TIMEOUT", "5")))
    filesystem_max_depth: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_FILESYSTEM_MAX_DEPTH", "4")))
    filesystem_max_results: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_FILESYSTEM_MAX_RESULTS", "100")))
    confirmation_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_CONFIRMATION_TIMEOUT", "30")))
    approved_roots_path: Path = field(default_factory=lambda: user_data_path("VoxPilot AI", ensure_exists=True) / "approved-roots.json")
    pdf_max_size_mb: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_MAX_SIZE_MB", "20")))
    pdf_max_pages: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_MAX_PAGES", "100")))
    pdf_max_characters: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_MAX_CHARACTERS", "200000")))
    pdf_min_characters: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_MIN_CHARACTERS", "20")))
    pdf_page_characters: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_PAGE_CHARACTERS", "20000")))
    pdf_extraction_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_PDF_EXTRACTION_TIMEOUT", "60")))
    pdf_summary_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_PDF_SUMMARY_TIMEOUT", "180")))
    pdf_max_chunks: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_MAX_CHUNKS", "20")))
    pdf_chunk_characters: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_CHUNK_CHARACTERS", "10000")))
    pdf_spoken_characters: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_SPOKEN_SUMMARY_MAX_CHARS", "300")))
    pdf_selection_timeout: float = field(default_factory=lambda: float(os.getenv("VOXPILOT_PDF_SELECTION_TIMEOUT", "60")))
    pdf_memory_mb: int = field(default_factory=lambda: int(os.getenv("VOXPILOT_PDF_MEMORY_MB", "512")))
