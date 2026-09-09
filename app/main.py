from __future__ import annotations

import logging
import sys
from dataclasses import replace

from PySide6.QtWidgets import QApplication

from app.agent.executor import CommandExecutor
from app.agent.router import CommandRouter
from app.config import Settings, load_project_env
from app.database.repository import HistoryRepository
from app.ui.main_window import MainWindow
from app.voice.tts import TextToSpeech
from app.voice.audio_devices import AudioDeviceService, DeviceSelectionStore
from app.voice.recorder import AudioRecorder
from app.voice.transcriber import SpeechTranscriber
from app.voice.voice_controller import VoiceCommandController
from app.voice.wake_word import WakeWordController


def main() -> int:
    load_project_env()
    settings = Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    application = QApplication(sys.argv)
    executor = CommandExecutor()
    device_service = AudioDeviceService(store=DeviceSelectionStore(settings.voice_settings_path), target_sample_rate=settings.sample_rate)
    transcriber = SpeechTranscriber(settings)
    wake_settings = replace(settings, save_audio=False, max_recording_seconds=settings.wake_window_seconds, initial_wait_seconds=settings.wake_window_seconds, silence_seconds=0.5, calibration_seconds=0.3)
    wake_controller = WakeWordController(AudioRecorder(wake_settings, device_service=device_service), transcriber)
    window = MainWindow(
        settings, executor, HistoryRepository(settings.database_path), TextToSpeech(settings.speech_enabled),
        device_service=device_service, recorder=AudioRecorder(settings, device_service=device_service), transcriber=transcriber,
        voice_controller=VoiceCommandController(CommandRouter(), executor), wake_controller=wake_controller,
    )
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
