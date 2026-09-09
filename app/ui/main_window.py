from __future__ import annotations

import logging
from threading import Event

from PySide6.QtCore import QThread, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from app.models import Status
from app.config import WAKE_PHRASE
from app.ui.microphone_settings import MicrophoneSettings
from app.ui.styles import DARK_STYLE
from app.ui.workers import CommandWorker, RecordingWorker, TranscriptionWorker, WakeWordWorker, VoiceSource, VoiceSignalRelay
from app.voice.wake_word import is_wake_phrase

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings, executor, repository, tts, device_service=None, recorder=None, transcriber=None, voice_controller=None, wake_controller=None):
        super().__init__()
        self.settings, self.executor, self.repository, self.tts = settings, executor, repository, tts
        self.device_service, self.recorder, self.transcriber, self.voice_controller = device_service, recorder, transcriber, voice_controller
        self.wake_controller = wake_controller
        self._active_thread = self._active_worker = None
        self._voice_thread = self._voice_worker = None
        self._voice_phase: str | None = None
        self._voice_result = None
        self._voice_source = VoiceSource.MANUAL
        self._cancelled = False
        self._voice_cancel = Event()
        self._wake_thread = self._wake_worker = None
        self._wake_cancel = Event(); self._wake_detected_pending = False; self._wake_command_pending = False; self._pending_action = None
        self._close_pending = False
        self._transition_generation = 0
        self._tts_pending = False
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
        self.wake_toggle = QCheckBox(f'Wake-word mode: "{WAKE_PHRASE}"')
        wake_store = getattr(self.device_service, "store", None)
        self.wake_toggle.setChecked(bool(wake_store and wake_store.wake_word_enabled()))
        self.wake_toggle.toggled.connect(self._toggle_wake_mode)
        self.command_panel = QTextEdit(); self.command_panel.setReadOnly(True); self.command_panel.setMaximumHeight(80)
        self.result_panel = QTextEdit(); self.result_panel.setReadOnly(True); self.result_panel.setMaximumHeight(120)
        self.history = QListWidget()
        for widget in (assistant, self.status, self.input): layout.addWidget(widget)
        layout.addLayout(buttons)
        if self.microphone_settings: layout.addWidget(self.microphone_settings)
        layout.addWidget(self.audio_level); layout.addWidget(self.speech); layout.addWidget(self.wake_toggle)
        for title, widget in (("Recognized or typed command", self.command_panel), ("Execution result", self.result_panel), ("Command history", self.history)):
            layout.addWidget(QLabel(title)); layout.addWidget(widget)
        root.setLayout(layout); self.setCentralWidget(root)
        if self.wake_toggle.isChecked(): QTimer.singleShot(0, self._start_wake_listener)

    def execute_command(self):
        if self._tts_pending: return
        if getattr(self.tts, "is_busy", lambda: False)():
            self._cancelled = False
            self._after_tts(self.execute_command); return
        if self._wake_thread is not None:
            if self._pending_action is None:
                self._pending_action = "typed"; self._set_busy_controls(); self._stop_wake_listener()
            return
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

    def start_voice_command(self, wake_initiated=False):
        if self._close_pending or (wake_initiated and (self._cancelled or not self.wake_toggle.isChecked())): return
        if self._tts_pending: return
        if getattr(self.tts, "is_busy", lambda: False)():
            self._cancelled = False
            self._after_tts(lambda: self.start_voice_command(wake_initiated)); return
        if self._wake_thread is not None:
            if self._pending_action is None:
                self._pending_action = "manual"; self._set_busy_controls(); self._stop_wake_listener()
            return
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
        self._voice_cancel = Event(); self._cancelled = False; self._voice_phase = "recording"; self._voice_result = None
        self._voice_source = VoiceSource.WAKE_COMMAND if wake_initiated else VoiceSource.MANUAL
        self._wake_command_pending = bool(wake_initiated)
        self._set_status(Status.COMMAND_LISTENING); self.result_panel.setText("Listening... Please remain quiet for calibration."); self._set_busy_controls()
        thread, worker = QThread(self), RecordingWorker(self.recorder, device, self._voice_cancel)
        self._voice_thread, self._voice_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run); worker.level_changed.connect(self._show_level); worker.status_changed.connect(self.result_panel.setText)
        relay = VoiceSignalRelay(self, worker)
        worker.finished.connect(relay.recording); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(self._voice_thread_finished); thread.finished.connect(thread.deleteLater); thread.start()

    def _start_transcription(self, recording):
        self._voice_phase = "transcribing"; self._voice_result = None
        self._set_status(Status.PROCESSING); self.result_panel.setText("Transcribing locally... Loading the speech model if needed.")
        thread, worker = QThread(self), TranscriptionWorker(self.transcriber, recording, self._voice_cancel, self._voice_source)
        self._voice_thread, self._voice_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run)
        relay = VoiceSignalRelay(self, worker)
        worker.result_ready.connect(relay.transcription)
        thread.finished.connect(relay.deleteLater)
        worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._voice_thread_finished); thread.finished.connect(thread.deleteLater); thread.start()

    @Slot(object)
    def _store_voice_result(self, result, worker=None):
        if worker is None or worker is not self._voice_worker or self._voice_phase != "recording":
            self._clear_audio(result); return
        self._voice_result = result

    @staticmethod
    def _clear_audio(result):
        audio = getattr(result, "audio", None)
        if audio is not None:
            audio.fill(0); result.audio = None

    @Slot(object, str)
    def _store_transcription_result(self, result, source, worker=None):
        if worker is None or worker is not self._voice_worker or self._voice_phase != "transcribing": return
        if source not in (VoiceSource.MANUAL, VoiceSource.WAKE_COMMAND) or source != self._voice_source: return
        if self._voice_cancel.is_set() or self._cancelled: return
        self._voice_result = result

    @Slot(str)
    def _wake_activation(self, text, worker=None):
        if worker is None or worker is not self._wake_worker: return
        if self._wake_cancel.is_set() or self._wake_detected_pending: return
        if is_wake_phrase(text): self._wake_detected()

    def _toggle_wake_mode(self, enabled):
        self._transition_generation += 1
        self._tts_pending = False
        store = getattr(self.device_service, "store", None)
        if store: store.save_wake_word_enabled(enabled)
        logger.info("Wake-word mode changed: enabled=%s", enabled)
        if enabled:
            self._cancelled = False; self._start_wake_listener()
        else:
            self._stop_wake_listener()
            self._set_idle_controls()

    def _start_wake_listener(self):
        if self._close_pending or self._tts_pending: return
        if not self.wake_toggle.isChecked() or self._wake_thread is not None or self._voice_thread is not None or self._active_thread is not None: return
        if getattr(self.tts, "is_busy", lambda: False)():
            self._after_tts(self._start_wake_listener); return
        if not self.wake_controller or not self.microphone_settings: return
        device = self.microphone_settings.selected_device()
        if device is None:
            self._wake_failure("No usable microphone is available for wake-word listening."); return
        if not self.transcriber.model_cached() and not self.transcriber.allow_download:
            answer = QMessageBox.question(self, "Local speech model required", "Wake-word fallback needs the local Whisper model. Download it once now?")
            if answer != QMessageBox.StandardButton.Yes:
                self.wake_toggle.setChecked(False); return
            self.transcriber.allow_download = True
        self._wake_cancel = Event(); self._wake_detected_pending = False
        thread, worker = QThread(self), WakeWordWorker(self.wake_controller, device, self._wake_cancel)
        self._wake_thread, self._wake_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run)
        relay = VoiceSignalRelay(self, worker, wake=True)
        worker.state_changed.connect(relay.state)
        worker.level_changed.connect(relay.level); worker.activation.connect(relay.activation)
        worker.failed.connect(relay.failure); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(self._wake_finished); thread.finished.connect(thread.deleteLater); thread.start()
        self._set_status(Status.WAKE_LISTENING); self.result_panel.setText(f'Wake-word listening for "{WAKE_PHRASE}".')
        self._set_idle_controls()

    def _stop_wake_listener(self):
        if self._wake_thread is not None:
            self._wake_cancel.set(); self._wake_thread.requestInterruption()

    def _wake_state_changed(self, state, worker=None):
        if worker is not self._wake_worker or self._wake_cancel.is_set() or self._wake_detected_pending: return
        self._set_status(Status.PROCESSING if state == "Processing" else Status.WAKE_LISTENING)

    def _wake_detected(self):
        if self._wake_cancel.is_set() or self._cancelled or self._pending_action: return
        self._wake_detected_pending = True
        self._set_busy_controls()
        self._set_status(Status.WAKE_DETECTED)
        self.result_panel.setText("Wake phrase detected.")
        logger.info("Wake phrase detected; listener paused")
        try: self.tts.speak("Yes, how can I help you?")
        except Exception: logger.exception("Wake acknowledgement speech failed")

    def _wake_failure(self, message):
        self.result_panel.setText(message); self._set_status(Status.FAILED)
        if self.microphone_settings: self.microphone_settings.refresh()

    def _wake_finished(self):
        if self.sender() is not None and self.sender() is not self._wake_thread: return
        detected = self._wake_detected_pending
        self._wake_thread = self._wake_worker = None; self._wake_detected_pending = False; self.audio_level.setValue(0)
        action, self._pending_action = self._pending_action, None
        if self._close_pending: QTimer.singleShot(0, self.close); return
        if action == "manual": QTimer.singleShot(0, self.start_voice_command); return
        if action == "typed": QTimer.singleShot(0, self.execute_command); return
        if detected:
            self._after_tts(lambda: self.start_voice_command(wake_initiated=True)); return
        if self.wake_toggle.isChecked() and not self._cancelled:
            QTimer.singleShot(round(self.settings.wake_word_cooldown * 1000), self._start_wake_listener)
        else: self._set_idle_controls()

    def _speech_guard_ms(self, text):
        speech_seconds = min(getattr(self.tts, "timeout", 8.0), max(0.8, len(text.split()) / 2.5)) if self.tts.enabled else 0.0
        return round((speech_seconds + self.settings.wake_word_cooldown) * 1000)

    def _after_tts(self, callback):
        generation = self._transition_generation
        self._tts_pending = True
        self._set_busy_controls()

        def valid():
            return generation == self._transition_generation and not self._cancelled and not self._close_pending

        def complete():
            if not valid(): return
            self._tts_pending = False
            callback()

        def wait_idle():
            if not valid(): return
            if getattr(self.tts, "is_busy", lambda: False)():
                QTimer.singleShot(100, wait_idle)
                return
            delay = round(self.settings.wake_word_cooldown * 1000) if self.tts.enabled else 0
            QTimer.singleShot(max(0, delay), complete)

        wait_idle()

    def _voice_thread_finished(self):
        if self.sender() is not None and self.sender() is not self._voice_thread: return
        phase, result = self._voice_phase, self._voice_result
        self._voice_thread = self._voice_worker = None; self._voice_result = None
        if self._close_pending:
            audio = getattr(result, "audio", None)
            if audio is not None:
                audio.fill(0); result.audio = None
            QTimer.singleShot(0, self.close); return
        if self._cancelled:
            audio = getattr(result, "audio", None)
            if audio is not None:
                audio.fill(0); result.audio = None
            self._voice_phase = None; self._wake_command_pending = False; self.audio_level.setValue(0); self._set_idle_controls(); return
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
        self._transition_generation += 1
        self._tts_pending = False
        self._pending_action = None
        self._wake_detected_pending = False
        self._cancelled = True
        if self.wake_toggle.isChecked(): self.wake_toggle.setChecked(False)
        if self._wake_thread is not None:
            self._stop_wake_listener(); self.result_panel.setText("Wake-word listening cancelled.")
        elif self._voice_thread is not None:
            self._voice_cancel.set(); self._voice_thread.requestInterruption(); self.result_panel.setText("Voice operation cancelled.")
        elif self._active_thread is not None:
            self._active_thread.requestInterruption(); self.result_panel.setText("Cancellation requested. The current safe operation will stop where possible.")
        else: self.result_panel.setText("No cancellable action is currently running.")
        self._set_status(Status.IDLE); self.audio_level.setValue(0)

    def _command_finished(self):
        self._wake_command_pending = False
        self._active_thread = self._active_worker = None; self._set_idle_controls()
        if self._close_pending: QTimer.singleShot(0, self.close)
        elif self.wake_toggle.isChecked(): self._after_tts(self._start_wake_listener)

    def _voice_failure(self, message):
        self._wake_command_pending = False
        self.result_panel.setText(message); self._set_status(Status.FAILED); self._set_idle_controls()
        if self.wake_toggle.isChecked(): QTimer.singleShot(round(self.settings.wake_word_cooldown * 1000), self._start_wake_listener)

    def _set_busy_controls(self):
        self.execute_button.setEnabled(False); self.microphone_button.setEnabled(False); self.input.setEnabled(False); self.stop_button.setEnabled(True)

    def _set_idle_controls(self):
        busy = self._active_thread is not None or self._voice_thread is not None or self._tts_pending
        self.execute_button.setEnabled(not busy); self.microphone_button.setEnabled(not busy and self.device_service is not None)
        self.input.setEnabled(not busy); self.stop_button.setEnabled(busy or self._wake_thread is not None)

    def _show_level(self, level): self.audio_level.setValue(max(0, min(100, round(level * 500))))
    def _toggle_speech(self, enabled): self.tts.enabled = enabled
    def _set_status(self, status): self.status.setText(f"Status: {status.value}")

    def _test_microphone(self, device):
        if self._wake_thread is not None or self._voice_thread is not None or self._tts_pending:
            self.result_panel.setText("Stop listening before testing the microphone."); return
        success, message = self.recorder.test_device(device)
        if not success and self.microphone_settings: self.microphone_settings.refresh()
        self.result_panel.setText(message); self._set_status(Status.COMPLETED if success else Status.FAILED)

    def _set_microphone_sensitivity(self, value):
        if self.recorder is not None: self.recorder.sensitivity = value
        if self.wake_controller is not None: self.wake_controller.recorder.sensitivity = value

    def _load_history(self):
        try:
            for row in self.repository.recent(): self.history.addItem(f"{row['status']}: {row['original_command']} — {row['result_message']}")
        except Exception: logger.exception("Could not load command history")

    def closeEvent(self, event):
        self._transition_generation += 1
        self._tts_pending = False
        self._cancelled = True; self._voice_cancel.set()
        self.wake_toggle.blockSignals(True); self.wake_toggle.setChecked(False); self.wake_toggle.blockSignals(False)
        self._wake_cancel.set()
        active = [thread for thread in (self._wake_thread, self._voice_thread, self._active_thread) if thread is not None]
        if active:
            self._close_pending = True
            for thread in active: thread.requestInterruption()
            event.ignore()
            return
        shutdown = getattr(self.tts, "shutdown", None)
        if shutdown: shutdown()
        shutdown = getattr(self.transcriber, "shutdown", None)
        if shutdown: shutdown()
        event.accept()
