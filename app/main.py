from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.agent.executor import CommandExecutor
from app.config import Settings
from app.database.repository import HistoryRepository
from app.ui.main_window import MainWindow
from app.voice.tts import TextToSpeech


def main() -> int:
    settings = Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    application = QApplication(sys.argv)
    window = MainWindow(settings, CommandExecutor(), HistoryRepository(settings.database_path), TextToSpeech(settings.speech_enabled))
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
