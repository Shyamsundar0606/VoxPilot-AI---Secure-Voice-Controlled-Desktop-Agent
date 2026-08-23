from __future__ import annotations

import logging

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from app.models import Status
from app.ui.styles import DARK_STYLE
from app.ui.workers import CommandWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings, executor, repository, tts):
        super().__init__()
        self.settings, self.executor, self.repository, self.tts = settings, executor, repository, tts
        self._active_thread: QThread | None = None
        self._active_worker: CommandWorker | None = None
        self._cancelled = False
        self.setWindowTitle(settings.app_name)
        self.resize(900, 680)
        self.setStyleSheet(DARK_STYLE)
        self._build_ui()
        self._load_history()

    def _build_ui(self):
        root, layout = QWidget(), QVBoxLayout()
        assistant = QLabel(self.settings.assistant_name)
        assistant.setObjectName("assistantLabel")
        self.status = QLabel("Status: Idle")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a safe command...")
        self.input.returnPressed.connect(self.execute_command)
        self.execute_button = QPushButton("Execute Command")
        self.execute_button.clicked.connect(self.execute_command)
        microphone = QPushButton("Microphone")
        microphone.clicked.connect(lambda: QMessageBox.information(self, "Milestone 1", "Voice recognition will be enabled in Milestone 2."))
        stop = QPushButton("Stop")
        stop.setObjectName("stopButton")
        stop.clicked.connect(self.stop)
        buttons = QHBoxLayout()
        for widget in (self.execute_button, microphone, stop):
            buttons.addWidget(widget)
        self.speech = QCheckBox("Enable spoken responses")
        self.speech.setChecked(self.tts.enabled)
        self.speech.toggled.connect(self._toggle_speech)
        self.command_panel = QTextEdit(); self.command_panel.setReadOnly(True); self.command_panel.setMaximumHeight(80)
        self.result_panel = QTextEdit(); self.result_panel.setReadOnly(True); self.result_panel.setMaximumHeight(110)
        self.history = QListWidget()
        for widget in (assistant, self.status, self.input):
            layout.addWidget(widget)
        layout.addLayout(buttons); layout.addWidget(self.speech)
        for title, widget in (("Recognized or typed command", self.command_panel), ("Execution result", self.result_panel), ("Command history", self.history)):
            layout.addWidget(QLabel(title)); layout.addWidget(widget)
        root.setLayout(layout); self.setCentralWidget(root)

    def execute_command(self):
        if self._active_thread is not None:
            self.result_panel.setText("A command is already processing.")
            return
        command = self.input.text().strip()
        if not command:
            self.result_panel.setText("Please enter a command."); self._set_status(Status.FAILED); return
        self.command_panel.setText(command); self._set_status(Status.PROCESSING)
        self._cancelled = False; self._set_controls_busy(True)
        thread, worker = QThread(self), CommandWorker(self.executor, command)
        self._active_thread, self._active_worker = thread, worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.finished.connect(self._complete)
        worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._worker_finished); thread.finished.connect(thread.deleteLater)
        thread.start()

    def _complete(self, result):
        try:
            if self._cancelled:
                return
            self.result_panel.setText(result.result_message)
            self._set_status(result.status)
            self.history.insertItem(0, f"{result.status.value}: {result.original_command} — {result.result_message}")
            self.input.clear()
            try:
                self.repository.add(result)
            except Exception:
                logger.exception("Could not save command history")
                self.result_panel.append("History could not be saved, but the command completed.")
            try:
                self.tts.speak(result.result_message)
            except Exception:
                logger.exception("Could not queue spoken response")
        finally:
            if self._active_thread is None:
                self._set_controls_busy(False)

    def stop(self):
        self._cancelled = True
        if self._active_thread is not None:
            self._active_thread.requestInterruption()
            self.result_panel.setText("Cancellation requested. The current safe operation will stop where possible.")
        else:
            self.result_panel.setText("No cancellable action is currently running.")
        self._set_status(Status.IDLE)

    def _worker_finished(self):
        self._active_thread = None; self._active_worker = None
        self._set_controls_busy(False)

    def _set_controls_busy(self, busy: bool):
        self.execute_button.setEnabled(not busy); self.input.setEnabled(not busy)

    def _toggle_speech(self, enabled): self.tts.enabled = enabled
    def _set_status(self, status): self.status.setText(f"Status: {status.value}")

    def _load_history(self):
        try:
            for row in self.repository.recent():
                self.history.addItem(f"{row['status']}: {row['original_command']} — {row['result_message']}")
        except Exception:
            logger.exception("Could not load command history")
