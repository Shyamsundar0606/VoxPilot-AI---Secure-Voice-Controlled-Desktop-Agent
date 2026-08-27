from __future__ import annotations

import logging
from threading import Event

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from app.models import Status
from app.ui.microphone_settings import MicrophoneSettings
from app.ui.styles import DARK_STYLE
from app.ui.workers import CommandWorker, RecordingWorker, TranscriptionWorker

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings, executor, repository, tts, device_service=None, recorder=None, transcriber=None, voice_controller=None):
        super().__init__()
        self.settings, self.executor, self.repository, self.tts = settings, executor, repository, tts
        self.device_service, self.recorder, self.transcriber, self.voice_controller = device_service, recorder, transcriber, voice_controller
        self._active_thread = self._active_worker = None
        self._voice_thread = self._voice_worker = None
        self._voice_phase: str | None = None
        self._voice_result = None
        self._cancelled = False
        self._voice_cancel = Event()
        self._close_pending = False
        self.setWindowTitle(settings.app_name); self.resize(900, 760); self.setStyleSheet(DARK_STYLE)
        self._build_ui(); self._load_history(); self._set_idle_controls()

    def _build_ui(self):
        root, layout = QWidget(), QVBoxLayout()
        assistant = QLabel(self.settings.assistant_name); assistant.setObjectName("assistantLabel")
        self.status = QLabel("Status: Idle")
        self.input = QLineEdit(); self.input.setPlaceholderText("Type a safe command..."); self.input.returnPressed.connect(self.execute_command)
        self.execute_button = QPushButton("Execute Command"); self.execute_button.clicked.connect(self.execute_command)
        self.microphone_button = QPushButton("Microphone"); self.microphone_button.clicked.connect(self.start_voice_command)
        self.stop_button = QPushButton("Stop"); self.stop_button.setObjectName("stopButton"); self.stop_button.clicked.connect(self.stop)
        buttons = QHBoxLayout()
        for widget in (self.execute_button, self.microphone_button, self.stop_button): buttons.addWidget(widget)
        self.audio_level = QProgressBar(); self.audio_level.setRange(0, 100); self.audio_level.setValue(0); self.audio_level.setFormat("Input level: %p%")
        self.microphone_settings = MicrophoneSettings(self.device_service) if self.device_service else None
        if self.microphone_settings:
            sensitivity_index = self.microphone_settings.sensitivity.findData(getattr(self.recorder, "sensitivity", "normal"))
            self.microphone_settings.sensitivity.setCurrentIndex(max(0, sensitivity_index))
            self.microphone_settings.test_requested.connect(self._test_microphone)
            self.microphone_settings.sensitivity_changed.connect(self._set_microphone_sensitivity)
        self.speech = QCheckBox("Enable spoken responses"); self.speech.setChecked(self.tts.enabled); self.speech.toggled.connect(self._toggle_speech)
        self.command_panel = QTextEdit(); self.command_panel.setReadOnly(True); self.command_panel.setMaximumHeight(80)
        self.result_panel = QTextEdit(); self.result_panel.setReadOnly(True); self.result_panel.setMaximumHeight(120)
        self.history = QListWidget()
        for widget in (assistant, self.status, self.input): layout.addWidget(widget)
        layout.addLayout(buttons)
        if self.microphone_settings: layout.addWidget(self.microphone_settings)
        layout.addWidget(self.audio_level); layout.addWidget(self.speech)
        for title, widget in (("Recognized or typed command", self.command_panel), ("Execution result", self.result_panel), ("Command history", self.history)):
            layout.addWidget(QLabel(title)); layout.addWidget(widget)
        root.setLayout(layout); self.setCentralWidget(root)

    def execute_command(self):
        if self._active_thread is not None or self._voice_thread is not None:
            self.result_panel.setText("Another command or voice operation is already active."); return
        command = self.input.text().strip()
        if not command:
            self.result_panel.setText("Please enter a command."); self._set_status(Status.FAILED); return
        self.command_panel.setText(command); self._set_status(Status.PROCESSING)
        self._cancelled = False; self._set_busy_controls()
        thread, worker = QThread(self), CommandWorker(self.executor, command)
        self._active_thread, self._active_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run); worker.finished.connect(self._complete)
        worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._command_finished); thread.finished.connect(thread.deleteLater); thread.start()

    def start_voice_command(self):
        if self._active_thread is not None or self._voice_thread is not None:
            self.result_panel.setText("Another command or recording is already active."); return
        if not all((self.device_service, self.recorder, self.transcriber, self.voice_controller, self.microphone_settings)):
            self._voice_failure("Voice input is not configured."); return
        device = self.microphone_settings.selected_device()
        if device is None:
            self._voice_failure("No input microphone is available."); return
        if not self.transcriber.model_cached() and not self.transcriber.allow_download:
            answer = QMessageBox.question(self, "Local speech model required", f"The local Whisper model '{self.settings.whisper_model_size}' is not cached. Download it once now? This requires internet access but no API key.")
            if answer != QMessageBox.StandardButton.Yes:
                self._voice_failure("The local speech model is required before voice commands can be used."); return
            self.transcriber.allow_download = True
            self.result_panel.setText("The local speech model will download and load during transcription.")
        self._voice_cancel.clear(); self._cancelled = False; self._voice_phase = "recording"; self._voice_result = None
        self._set_status(Status.LISTENING); self.result_panel.setText("Listening... Please remain quiet for calibration."); self._set_busy_controls()
        thread, worker = QThread(self), RecordingWorker(self.recorder, device, self._voice_cancel)
        self._voice_thread, self._voice_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run); worker.level_changed.connect(self._show_level); worker.status_changed.connect(self.result_panel.setText)
        worker.finished.connect(self._store_voice_result); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._voice_thread_finished); thread.finished.connect(thread.deleteLater); thread.start()

    def _start_transcription(self, recording):
        self._voice_phase = "transcribing"; self._voice_result = None
        self._set_status(Status.PROCESSING); self.result_panel.setText("Transcribing locally... Loading the speech model if needed.")
        thread, worker = QThread(self), TranscriptionWorker(self.transcriber, recording, self._voice_cancel)
        self._voice_thread, self._voice_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run); worker.finished.connect(self._store_voice_result)
        worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._voice_thread_finished); thread.finished.connect(thread.deleteLater); thread.start()

    def _store_voice_result(self, result): self._voice_result = result

    def _voice_thread_finished(self):
        phase, result = self._voice_phase, self._voice_result
        self._voice_thread = self._voice_worker = None; self._voice_result = None
        if self._close_pending:
            audio = getattr(result, "audio", None)
            if audio is not None:
                audio.fill(0); result.audio = None
            QTimer.singleShot(0, self.close); return
        if self._cancelled:
            self._voice_phase = None; self.audio_level.setValue(0); self._set_idle_controls(); return
        if phase == "recording":
            if result is not None and result.success:
                self._start_transcription(result)
            else:
                if result is not None and result.error_code == "invalid_device" and self.microphone_settings:
                    self.microphone_settings.refresh()
                self._voice_phase = None; self._voice_failure(result.message if result else "Recording failed safely.")
            return
        self._voice_phase = None; self.audio_level.setValue(0)
        if result is None or not result.success:
            self._voice_failure(result.message if result else "Transcription failed safely."); return
        self.input.setText(result.text); self.command_panel.setText(result.text)
        command, error = self.voice_controller.approved_command(result)
        if error:
            self._voice_failure(error); return
        self._set_idle_controls(); self.input.setText(command); self.execute_command()

    def _complete(self, result):
        try:
            if self._cancelled: return
            self.result_panel.setText(result.result_message); self._set_status(result.status)
            self.history.insertItem(0, f"{result.status.value}: {result.original_command} — {result.result_message}"); self.input.clear()
            try: self.repository.add(result)
            except Exception:
                logger.exception("Could not save command history"); self.result_panel.append("History could not be saved, but the command completed.")
            try: self.tts.speak(result.result_message)
            except Exception: logger.exception("Could not queue spoken response")
        finally:
            if self._active_thread is None: self._set_idle_controls()

    def stop(self):
        self._cancelled = True
        if self._voice_thread is not None:
            self._voice_cancel.set(); self._voice_thread.requestInterruption(); self.result_panel.setText("Voice operation cancelled.")
        elif self._active_thread is not None:
            self._active_thread.requestInterruption(); self.result_panel.setText("Cancellation requested. The current safe operation will stop where possible.")
        else: self.result_panel.setText("No cancellable action is currently running.")
        self._set_status(Status.IDLE); self.audio_level.setValue(0)

    def _command_finished(self):
        self._active_thread = self._active_worker = None; self._set_idle_controls()
        if self._close_pending: QTimer.singleShot(0, self.close)

    def _voice_failure(self, message):
        self.result_panel.setText(message); self._set_status(Status.FAILED); self._set_idle_controls()

    def _set_busy_controls(self):
        self.execute_button.setEnabled(False); self.microphone_button.setEnabled(False); self.input.setEnabled(False); self.stop_button.setEnabled(True)

    def _set_idle_controls(self):
        busy = self._active_thread is not None or self._voice_thread is not None
        self.execute_button.setEnabled(not busy); self.microphone_button.setEnabled(not busy and self.device_service is not None)
        self.input.setEnabled(not busy); self.stop_button.setEnabled(busy)

    def _show_level(self, level): self.audio_level.setValue(max(0, min(100, round(level * 500))))
    def _toggle_speech(self, enabled): self.tts.enabled = enabled
    def _set_status(self, status): self.status.setText(f"Status: {status.value}")

    def _test_microphone(self, device):
        success, message = self.recorder.test_device(device)
        if not success and self.microphone_settings: self.microphone_settings.refresh()
        self.result_panel.setText(message); self._set_status(Status.COMPLETED if success else Status.FAILED)

    def _set_microphone_sensitivity(self, value):
        if self.recorder is not None: self.recorder.sensitivity = value

    def _load_history(self):
        try:
            for row in self.repository.recent(): self.history.addItem(f"{row['status']}: {row['original_command']} — {row['result_message']}")
        except Exception: logger.exception("Could not load command history")

    def closeEvent(self, event):
        self._cancelled = True; self._voice_cancel.set()
        active = [thread for thread in (self._voice_thread, self._active_thread) if thread is not None]
        if active:
            self._close_pending = True
            for thread in active: thread.requestInterruption()
            event.ignore()
            return
        event.accept()
