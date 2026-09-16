from __future__ import annotations

import logging
import sys
from dataclasses import replace

from PySide6.QtWidgets import QApplication

from app.agent.executor import CommandExecutor
from app.agent.router import CommandRouter
from app.agent.intent_planner import IntentPlanner
from app.agent.ollama_client import OllamaClient
from app.config import Settings, load_project_env
from app.database.repository import HistoryRepository
from app.ui.main_window import MainWindow
from app.voice.tts import TextToSpeech
from app.voice.audio_devices import AudioDeviceService, DeviceSelectionStore
from app.voice.recorder import AudioRecorder
from app.voice.transcriber import SpeechTranscriber
from app.voice.voice_controller import VoiceCommandController
from app.voice.wake_word import WakeWordController
from app.filesystem.roots import ApprovedRoots
from app.filesystem.service import FilesystemService
from app.security.confirmations import Confirmations
from app.tools.registry import ToolRegistry
from app.documents.service import DocumentService
from app.documents.limits import PdfLimits
from app.projects.service import ProjectService
from app.projects.profiles import Profiles
from app.projects.processes import ProcessManager
from app.projects.discovery import DiscoveryLimits


def main() -> int:
    load_project_env()
    settings = replace(Settings(), save_audio=False)
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    application = QApplication(sys.argv)
    planner = IntentPlanner(OllamaClient(settings.ollama_base_url, settings.intent_model, timeout=settings.intent_timeout), settings.intent_min_confidence)
    filesystem = FilesystemService(ApprovedRoots(settings.approved_roots_path), timeout=settings.filesystem_timeout,
        max_depth=settings.filesystem_max_depth, max_results=settings.filesystem_max_results)
    executor = CommandExecutor(planner=planner, registry=ToolRegistry(filesystem=filesystem),
        projects=ProjectService(filesystem.roots, Profiles(filesystem.roots, settings.project_profiles_path),
            ProcessManager(settings.project_output_max_bytes, settings.project_output_max_lines, settings.project_stop_timeout, settings.project_output_retention),
            DiscoveryLimits(settings.project_discovery_depth, settings.project_discovery_limit, settings.project_result_limit, settings.project_discovery_timeout),
            settings.project_confirmation_timeout),
        confirmations=Confirmations(settings.confirmation_timeout),
        documents=DocumentService(filesystem.roots, OllamaClient(settings.ollama_base_url, settings.primary_model), PdfLimits.from_settings(settings)))
    device_service = AudioDeviceService(store=DeviceSelectionStore(settings.voice_settings_path), target_sample_rate=settings.sample_rate)
    transcriber = SpeechTranscriber(settings)
    wake_controller = WakeWordController(settings, device_service)
    window = MainWindow(
        settings, executor, HistoryRepository(settings.database_path), TextToSpeech(settings.speech_enabled),
        device_service=device_service, recorder=AudioRecorder(settings, device_service=device_service), transcriber=transcriber,
        voice_controller=VoiceCommandController(CommandRouter(), executor, allow_intent_planning=True), wake_controller=wake_controller,
    )
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
