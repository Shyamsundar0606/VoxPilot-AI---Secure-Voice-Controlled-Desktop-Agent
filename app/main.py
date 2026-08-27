from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.agent.executor import CommandExecutor
from app.agent.router import CommandRouter
from app.config import Settings
from app.database.repository import HistoryRepository
from app.ui.main_window import MainWindow
from app.voice.tts import TextToSpeech
from app.voice.audio_devices import AudioDeviceService, DeviceSelectionStore
from app.voice.recorder import AudioRecorder
from app.voice.transcriber import SpeechTranscriber
from app.voice.voice_controller import VoiceCommandController


def main() -> int:
    settings = Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    application = QApplication(sys.argv)
    executor = CommandExecutor()
    device_service = AudioDeviceService(store=DeviceSelectionStore(settings.voice_settings_path), target_sample_rate=settings.sample_rate)
    window = MainWindow(
        settings, executor, HistoryRepository(settings.database_path), TextToSpeech(settings.speech_enabled),
        device_service=device_service, recorder=AudioRecorder(settings, device_service=device_service), transcriber=SpeechTranscriber(settings),
        voice_controller=VoiceCommandController(CommandRouter(), executor),
    )
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
