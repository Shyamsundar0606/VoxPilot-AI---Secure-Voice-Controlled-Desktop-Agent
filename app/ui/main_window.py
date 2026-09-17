from __future__ import annotations

import logging
import re
from threading import Event

from PySide6.QtCore import QThread, QTimer, Slot, Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget, QFileDialog, QComboBox, QInputDialog, QScrollArea,
)

from app.models import Status
from app.config import WAKE_PHRASE
from app.ui.microphone_settings import MicrophoneSettings
from app.ui.styles import DARK_STYLE
from app.ui.workers import CommandWorker, RecordingWorker, TranscriptionWorker, WakeWordWorker, VoiceSource, VoiceSignalRelay, ProjectRootWorker, CommandSignalRelay
from app.voice.wake_word import is_wake_phrase

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings, executor, repository, tts, device_service=None, recorder=None, transcriber=None, voice_controller=None, wake_controller=None):
        super().__init__()
        self.settings, self.executor, self.repository, self.tts = settings, executor, repository, tts
        self.wake_phrase = getattr(settings, "wake_phrase", WAKE_PHRASE)
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
        self._wake_retry = QTimer(self)
        self._wake_retry.setSingleShot(True)
        self._wake_retry.timeout.connect(self._start_wake_listener)
        self._wake_cancel = Event(); self._wake_detected_pending = False; self._wake_command_pending = False; self._pending_action = None
        self._close_pending = False
        self._transition_generation = 0
        self._tts_pending = False
        self._confirmation = None
        self._document_selection = None
        self._voice_selection_token = None
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.timeout.connect(lambda: self._cancel_pdf_selection("PDF selection expired."))
        self._voice_confirmation_token = None
        self._confirmation_timer = QTimer(self)
        self._confirmation_timer.setSingleShot(True)
        self._confirmation_timer.timeout.connect(lambda: self._cancel_confirmation("Confirmation expired."))
        self._project_output_timer = QTimer(self)
        self._project_output_timer.setSingleShot(True)
        self._project_output_timer.timeout.connect(lambda: self.project_output.clear())
        self.setWindowTitle(settings.app_name); self.resize(900, 760); self.setStyleSheet(DARK_STYLE)
        self._build_ui(); self._load_history(); self._set_idle_controls()

    def _build_ui(self):
        root, layout = QWidget(), QVBoxLayout()
        assistant = QLabel(self.settings.assistant_name); assistant.setObjectName("assistantLabel")
        self.status = QLabel("Status: Idle")
        self.document_progress = QLabel("")
        self.document_progress.hide()
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
        self.wake_toggle = QCheckBox(f'Wake-word mode: "{self.wake_phrase}"')
        self.wake_notice = QLabel(""); self.wake_notice.setWordWrap(True); self.wake_notice.hide()
        wake_store = getattr(self.device_service, "store", None)
        self.wake_toggle.setChecked(bool(wake_store and wake_store.wake_word_enabled()))
        self.wake_toggle.toggled.connect(self._toggle_wake_mode)
        self.command_panel = QTextEdit(); self.command_panel.setReadOnly(True); self.command_panel.setMaximumHeight(80)
        self.result_panel = QTextEdit(); self.result_panel.setReadOnly(True); self.result_panel.setMaximumHeight(120)
        self.pdf_choices = QListWidget()
        self.pdf_choices.setMaximumHeight(120)
        self.pdf_select_button = QPushButton("Summarize selected PDF")
        self.pdf_select_button.clicked.connect(lambda: self._select_pdf(self.pdf_choices.currentRow() + 1))
        self.pdf_choices.hide(); self.pdf_select_button.hide()
        self.history = QListWidget()
        self.confirmation_panel = QWidget()
        confirmation_layout = QVBoxLayout(self.confirmation_panel)
        self.confirmation_label = QLabel()
        self.confirm_button = QPushButton("Confirm")
        self.cancel_confirmation_button = QPushButton("Cancel")
        self.confirm_button.clicked.connect(self._confirm_creation)
        self.cancel_confirmation_button.clicked.connect(lambda: self._cancel_confirmation("Folder creation cancelled."))
        for widget in (self.confirmation_label, self.confirm_button, self.cancel_confirmation_button): confirmation_layout.addWidget(widget)
        self.confirmation_panel.hide()
        self.project_button = QPushButton("Approve project folder")
        self.project_button.clicked.connect(self._select_project_root)
        self.project_button.setText("Approve projects folder")
        self.project_selector = QComboBox()
        self.project_state = QLabel("No project selected")
        self.project_selector.currentIndexChanged.connect(self._project_selection_changed)
        self.project_controls = []
        project_buttons = QHBoxLayout()
        for title, action in (("Refresh projects", "list"), ("Open project", "open"), ("Start project", "start"),
                              ("Stop project", "stop"), ("Refresh process output", "running"), ("Save launch profile", "profile")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, action=action: self._project_action(action))
            self.project_controls.append(button); project_buttons.addWidget(button)
        self.project_output = QTextEdit(); self.project_output.setReadOnly(True); self.project_output.setMaximumHeight(100)
        self.project_output.document().setMaximumBlockCount(getattr(self.settings, "project_output_max_lines", 500))
        for widget in (assistant, self.status, self.input): layout.addWidget(widget)
        layout.addWidget(self.document_progress)
        layout.addLayout(buttons)
        if self.microphone_settings: layout.addWidget(self.microphone_settings)
        layout.addWidget(self.audio_level); layout.addWidget(self.speech); layout.addWidget(self.wake_toggle)
        layout.addWidget(self.wake_notice)
        layout.addWidget(self.project_button); layout.addWidget(self.confirmation_panel)
        layout.addWidget(QLabel("Project management")); layout.addWidget(self.project_selector)
        layout.addWidget(self.project_state); layout.addLayout(project_buttons)
        layout.addWidget(QLabel("Process output (Refresh process output to update)")); layout.addWidget(self.project_output)
        from app.ui.knowledge_panel import KnowledgePanel
        self.knowledge_panel = KnowledgePanel(self)
        layout.addWidget(self.knowledge_panel)
        from app.ui.locations_panel import LocationsPanel
        self.locations_panel = LocationsPanel(self)
        layout.addWidget(self.locations_panel)
        layout.addWidget(self.pdf_choices); layout.addWidget(self.pdf_select_button)
        for title, widget in (("Recognized or typed command", self.command_panel), ("Execution result", self.result_panel), ("Command history", self.history)):
            layout.addWidget(QLabel(title)); layout.addWidget(widget)
        root.setLayout(layout)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(root)
        self.setCentralWidget(scroll)
        if self.wake_toggle.isChecked(): QTimer.singleShot(0, self._start_wake_listener)

    def execute_command(self):
        response = self.input.text().strip().casefold().rstrip(".!?")
        if self._confirmation and self._confirmation.get("kind") in {"project", "knowledge"} and response == "stop":
            self.stop(); self.input.clear(); return
        if self._confirmation and self._confirmation.get("kind") in {"project", "knowledge"} and response in {"yes", "no", "confirm", "cancel"}:
            if response in {"yes", "confirm"}: self._confirm_creation()
            else: self._cancel_confirmation("Index action cancelled." if self._confirmation.get('kind') == 'knowledge' else "Project action cancelled.")
            self.input.clear(); return
        if response in {"yes", "no"}:
            self.status.setToolTip("There is no pending project confirmation."); self.input.clear(); return
        if response in {"cancel pdf summarization", "cancel document task"} or (self._document_selection and response == "cancel"):
            self.stop(); return
        if self._document_selection:
            number = self._selection_number(response)
            if number is not None:
                self._select_pdf(number); return
            self._cancel_pdf_selection(resume=False)
        if response in {"confirm", "cancel"}:
            if self._confirmation:
                if response == "confirm": self._confirm_creation()
                else: self._cancel_confirmation("Folder creation cancelled.")
            else: self.result_panel.setText("There is no pending confirmation.")
            return
        if self._confirmation: self._cancel_confirmation("Previous confirmation cancelled.", resume=False)
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
        self.command_panel.setPlainText(command); self._set_status(Status.PROCESSING)
        self._cancelled = False; self._set_busy_controls()
        self._launch_command_worker(CommandWorker(self.executor, command))

    def _launch_command_worker(self, worker):
        thread = QThread(self)
        self._active_thread, self._active_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run)
        relay = CommandSignalRelay(self, worker)
        worker.finished.connect(relay.complete)
        if isinstance(worker, CommandWorker): worker.progress.connect(relay.progress)
        thread.finished.connect(relay.deleteLater)
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
            self.status.setToolTip("The local speech model will download and load during transcription.")
        self._voice_cancel = Event(); self._cancelled = False; self._voice_phase = "recording"; self._voice_result = None
        self._voice_source = VoiceSource.WAKE_COMMAND if wake_initiated else VoiceSource.MANUAL
        self._voice_confirmation_token = self._confirmation["token"] if self._confirmation else None
        self._voice_selection_token = self._document_selection["token"] if self._document_selection else None
        self._wake_command_pending = bool(wake_initiated)
        self._set_status(Status.COMMAND_LISTENING); self._recording_progress("Listening... Please remain quiet for calibration."); self._set_busy_controls()
        thread, worker = QThread(self), RecordingWorker(self.recorder, device, self._voice_cancel)
        self._voice_thread, self._voice_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run); worker.level_changed.connect(self._show_level); worker.status_changed.connect(self._recording_progress)
        relay = VoiceSignalRelay(self, worker)
        worker.finished.connect(relay.recording); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(self._voice_thread_finished); thread.finished.connect(thread.deleteLater); thread.start()

    def _start_transcription(self, recording):
        self._voice_phase = "transcribing"; self._voice_result = None
        self._set_status(Status.PROCESSING); self.status.setToolTip("Transcribing locally... Loading the speech model if needed.")
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
        if is_wake_phrase(text, self.wake_phrase): self._wake_detected()

    def _toggle_wake_mode(self, enabled):
        self._wake_retry.stop()
        self._transition_generation += 1
        self._tts_pending = False
        store = getattr(self.device_service, "store", None)
        if store: store.save_wake_word_enabled(enabled)
        logger.info("Wake-word mode changed: enabled=%s", enabled)
        if enabled:
            self._cancelled = False; self._start_wake_listener()
        else:
            self._wake_detected_pending = False
            self._wake_command_pending = False
            self._stop_wake_listener()
            self._set_idle_controls()

    def _start_wake_listener(self):
        self._wake_retry.stop()
        if self._document_selection: return
        if self._confirmation: return
        if self._close_pending or self._tts_pending: return
        if not self.wake_toggle.isChecked() or self._wake_thread is not None or self._voice_thread is not None or self._active_thread is not None: return
        if getattr(self.tts, "is_busy", lambda: False)():
            self._after_tts(self._start_wake_listener); return
        if not self.wake_controller or not self.microphone_settings: return
        device = self.microphone_settings.selected_device()
        if device is None:
            self._wake_failure("No usable microphone is available. Reconnect or select a microphone; wake listening will retry.")
            self._wake_retry.start(2000); return
        self._wake_cancel = Event(); self._wake_detected_pending = False
        thread, worker = QThread(self), WakeWordWorker(self.wake_controller, device, self._wake_cancel)
        self._wake_thread, self._wake_worker = thread, worker
        worker.moveToThread(thread); thread.started.connect(worker.run)
        relay = VoiceSignalRelay(self, worker, wake=True)
        worker.state_changed.connect(relay.state)
        worker.level_changed.connect(relay.level); worker.activation.connect(relay.activation)
        worker.failed.connect(relay.failure); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        worker.setup_failed.connect(relay.setup_failure)
        thread.finished.connect(relay.deleteLater)
        thread.finished.connect(self._wake_finished); thread.finished.connect(thread.deleteLater); thread.start()
        self._set_status(Status.WAKE_LISTENING)
        self._set_idle_controls()

    def _stop_wake_listener(self):
        if self._wake_thread is not None:
            self._wake_cancel.set(); self._wake_thread.requestInterruption()

    def _wake_state_changed(self, state, worker=None):
        if worker is not self._wake_worker or self._wake_cancel.is_set() or self._wake_detected_pending: return
        self.wake_notice.clear(); self.wake_notice.hide()
        self._set_status(Status.PROCESSING if state == "Processing" else Status.WAKE_LISTENING)

    def _wake_detected(self):
        if self._wake_cancel.is_set() or self._cancelled or self._pending_action: return
        self._wake_detected_pending = True
        self._set_busy_controls()
        self._set_status(Status.WAKE_DETECTED)
        logger.info("Wake phrase detected; listener paused")
        try: self.tts.speak("Yes, how can I help you?")
        except Exception: logger.exception("Wake acknowledgement speech failed")

    def _wake_failure(self, message):
        self._set_status(Status.FAILED); self.status.setToolTip(message)
        self.wake_notice.setText(message); self.wake_notice.show()
        if self.microphone_settings: self.microphone_settings.refresh()

    def _wake_setup_failure(self, message):
        self._wake_failure(message)
        self.wake_toggle.setChecked(False)

    def _wake_finished(self):
        if self.sender() is not None and self.sender() is not self._wake_thread: return
        detected = self._wake_detected_pending
        self._wake_thread = self._wake_worker = None; self._wake_detected_pending = False; self.audio_level.setValue(0)
        action, self._pending_action = self._pending_action, None
        if self._close_pending: QTimer.singleShot(0, self.close); return
        if action == "manual": QTimer.singleShot(0, self.start_voice_command); return
        if action == "typed": QTimer.singleShot(0, self.execute_command); return
        if action == 'knowledge_open': QTimer.singleShot(0, self.knowledge_panel.open_source); return
        if detected:
            self._after_tts(lambda: self.start_voice_command(wake_initiated=True)); return
        if self.wake_toggle.isChecked() and not self._cancelled:
            self._wake_retry.start(max(1000, round(self.settings.wake_word_cooldown * 1000)))
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
        if self._voice_confirmation_token is not None:
            token, self._voice_confirmation_token = self._voice_confirmation_token, None
            if not self._confirmation or self._confirmation["token"] != token:
                self._voice_failure("That confirmation is no longer active."); return
            if result.text.strip().casefold().rstrip(".!?") in {"confirm", "cancel", "yes", "no", "stop"}:
                self.input.setText(result.text); self.execute_command(); return
        if self._document_selection or self._voice_selection_token:
            selection_token, self._voice_selection_token = self._voice_selection_token, None
            if not self._document_selection or selection_token != self._document_selection["token"]:
                self._set_idle_controls()
                return
            if self._selection_number(result.text) is not None or result.text.strip().casefold().rstrip(".!?") == "cancel":
                self.input.setText(result.text); self.execute_command(); return
        if result.text.strip().casefold().rstrip(".!?") in {"confirm", "cancel", "yes", "no"}:
            self.input.setText(result.text); self.execute_command(); return
        self.input.setText(result.text); self.command_panel.setText(result.text)
        command, error = self.voice_controller.approved_command(result)
        if error:
            self._voice_failure(error); return
        self._set_idle_controls(); self.input.setText(command); self.execute_command()

    def _complete(self, result):
        try:
            if self._cancelled: return
            if result.selected_tool == 'approved_locations':
                self.locations_panel.complete(result)
            if result.selected_tool == 'knowledge_operation':
                self.knowledge_panel.complete(result)
            self.document_progress.clear(); self.document_progress.hide()
            if result.document_failure_code is not None:
                from app.documents.errors import DocumentError
                # Display only the local message catalog, never child exception text.
                self.result_panel.setPlainText(str(DocumentError(result.document_failure_code)))
                self._set_status(result.status); self.input.clear()
                return
            if result.document_selection:
                self._document_selection = result.document_selection
                self.pdf_choices.clear()
                self.pdf_choices.addItems([f"{i + 1}. {label}" for i, label in enumerate(result.document_selection["labels"])])
                self.pdf_choices.show(); self.pdf_select_button.show()
                self.pdf_select_button.setText("Select indexed document" if result.document_selection.get('kind') == 'knowledge' else "Select project" if result.document_selection.get("kind") == "project" else "Summarize selected PDF")
                self._selection_timer.start(round(result.document_selection["timeout"] * 1000))
                self.result_panel.setPlainText(result.result_message)
                self._set_status(Status.AWAITING_PROJECT_SELECTION if result.document_selection.get("kind") == "project" else Status.AWAITING_SELECTION); self.input.clear()
                return
            if result.confirmation:
                self._confirmation = result.confirmation
                project = result.confirmation.get("kind") in {"project", "knowledge"}
                self.confirmation_label.setTextFormat(Qt.TextFormat.PlainText)
                self.confirmation_label.setText(result.confirmation["details"] if project else f"Create folder: {result.confirmation['folder_name']}\nParent: {result.confirmation['parent']}")
                self.confirmation_panel.show()
                self.input.clear()
                self._confirmation_timer.start(round(result.confirmation["timeout"] * 1000))
                self.result_panel.setPlainText("Review the index action, then Yes or No (or Confirm / Cancel)." if result.confirmation.get('kind') == 'knowledge' else "Review the exact project plan, then Yes or No (or Confirm / Cancel)." if project else "Review the exact location, then Confirm or Cancel. You can also use Microphone to say Confirm or Cancel.")
                self._set_status(Status.AWAITING_CONFIRMATION)
                return
            if not result.store_history:
                if result.project_data:
                    if "projects" in result.project_data:
                        self.project_selector.clear()
                        for item in result.project_data["projects"]:
                            self.project_selector.addItem(f"{item['name']} — {item['root']}/{item['relative']}", item)
                    if "running" in result.project_data:
                        rows = result.project_data["running"]
                        cap = getattr(self.settings, "project_output_max_bytes", 262144)
                        output = "\n".join(f"{row['name']} ({row['state']}):\n{row['output']}" for row in rows)
                        self.project_output.setPlainText(output.encode("utf-8")[-cap:].decode("utf-8", "replace"))
                        self._project_output_timer.start(round(getattr(self.settings, "project_output_retention", 60) * 1000))
                        self.project_state.setText("; ".join(f"{r['name']}: {r['state']}" for r in rows) or "No running projects")
                self.result_panel.setPlainText(result.result_message); self._set_status(result.status)
                self.input.clear()
                if result.selected_tool is not None:
                    # Speak a short summary, not full directory listings.
                    if result.selected_tool in {"summarize_pdf", "knowledge_operation"}:
                        if self.tts.enabled and result.spoken_message: self.tts.speak(result.spoken_message)
                    elif result.selected_tool == "project_operation": self.tts.speak("Project operation completed." if result.status == Status.COMPLETED else result.result_message)
                    else: self.tts.speak("File operation completed." if result.status == Status.COMPLETED else result.result_message)
                return
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
        knowledge_active = getattr(self._active_worker, 'source', None) == 'knowledge'
        project_active = bool((self._document_selection and self._document_selection.get("kind") == "project") or
            (self._confirmation and self._confirmation.get("kind") == "project") or getattr(self._active_worker, "source", None) == "project")
        document_active = bool((self._document_selection and self._document_selection.get("kind") != "project") or (isinstance(self._active_worker, CommandWorker) and
            (self._active_worker.is_document_task or self.status.text() in {"Status: Locating PDF", "Status: Extracting PDF", "Status: Summarizing"})))
        self._cancel_pdf_selection(resume=False)
        self.document_progress.clear(); self.document_progress.hide()
        self._cancel_confirmation("Folder creation cancelled.", resume=False)
        self._transition_generation += 1
        self._tts_pending = False
        self._pending_action = None
        self._wake_detected_pending = False
        self._cancelled = True
        if self.wake_toggle.isChecked(): self.wake_toggle.setChecked(False)
        if self._wake_thread is not None:
            self._stop_wake_listener()
        elif self._voice_thread is not None:
            self._voice_cancel.set(); self._voice_thread.requestInterruption(); self.result_panel.setText("Voice operation cancelled.")
        elif self._active_thread is not None:
            if isinstance(self._active_worker, (CommandWorker, ProjectRootWorker)): self._active_worker.cancel_event.set()
            self._active_thread.requestInterruption(); self.result_panel.setText("Cancellation requested. The current safe operation will stop where possible.")
        else: self.result_panel.setText("No cancellable action is currently running.")
        if document_active: self.result_panel.setPlainText("Document task cancelled.")
        if project_active: self.result_panel.setPlainText("Project operation cancelled. Already launched projects remain running.")
        if knowledge_active: self.knowledge_progress.setText('Knowledge operation cancelled; incomplete updates will be rolled back.')
        stop_speech = getattr(self.tts, "stop", None)
        if stop_speech: stop_speech()
        self._set_status(Status.CANCELLED if document_active else Status.IDLE); self.audio_level.setValue(0)

    def _command_finished(self):
        if self.sender() is not None and self.sender() is not self._active_thread: return
        self._wake_command_pending = False
        self._active_thread = self._active_worker = None; self._set_idle_controls()
        if self._close_pending: QTimer.singleShot(0, self.close)
        elif self.wake_toggle.isChecked() and not self._confirmation and not self._document_selection: self._after_tts(self._start_wake_listener)

    def _voice_failure(self, message):
        self._wake_command_pending = False
        self.result_panel.setText(message); self._set_status(Status.FAILED); self._set_idle_controls()
        if self.wake_toggle.isChecked() and not self._confirmation: QTimer.singleShot(round(self.settings.wake_word_cooldown * 1000), self._start_wake_listener)

    def _set_busy_controls(self):
        self.locations_panel.set_busy(True)
        self.knowledge_panel.set_busy(True)
        for button in self.project_controls: button.setEnabled(False)
        self.pdf_select_button.setEnabled(False)
        self.project_button.setEnabled(False); self.confirm_button.setEnabled(False)
        self.execute_button.setEnabled(False); self.microphone_button.setEnabled(False); self.input.setEnabled(False); self.stop_button.setEnabled(True)

    def _set_idle_controls(self):
        busy = self._active_thread is not None or self._voice_thread is not None or self._tts_pending
        self.locations_panel.set_busy(busy or self._wake_thread is not None)
        self.knowledge_panel.set_busy(busy)
        for button in self.project_controls: button.setEnabled(not busy)
        self.execute_button.setEnabled(not busy); self.microphone_button.setEnabled(not busy and self.device_service is not None)
        self.input.setEnabled(not busy); self.stop_button.setEnabled(busy or self._wake_thread is not None)
        self.project_button.setEnabled(not busy and self._wake_thread is None)
        self.confirm_button.setEnabled(not busy and self._confirmation is not None)
        self.pdf_select_button.setEnabled(not busy and self._document_selection is not None)
        if self._document_selection: self.stop_button.setEnabled(True)
        if self._confirmation: self.stop_button.setEnabled(True)

    @staticmethod
    def _selection_number(text):
        value = text.strip().casefold().rstrip(".!?")
        match = re.fullmatch(r"(?:(?:select|choose|option|number) )?(\d+|one|two|three|four|five|six|seven|eight|nine|ten)", value)
        if not match: return None
        word = match[1]
        return int(word) if word.isdigit() else ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"].index(word) + 1

    def _cancel_pdf_selection(self, message="", resume=True):
        pending, self._document_selection = self._document_selection, None
        if pending and pending.get("kind") == "project": message = message.replace("PDF", "Project")
        self._selection_timer.stop(); self.pdf_choices.hide(); self.pdf_select_button.hide(); self.pdf_choices.clear()
        from app.agent.executor import CommandExecutor
        if isinstance(self.executor, CommandExecutor) and self.executor.documents:
            self.executor.documents.cancel_selection()
        if pending and pending.get("kind") == "project" and self.executor.projects: self.executor.projects.cancel()
        if pending and pending.get('kind') == 'knowledge' and self.executor.knowledge: self.executor.knowledge.cancel()
        if pending:
            if message: self.result_panel.setPlainText(message)
            self._set_idle_controls()
            if resume and self.wake_toggle.isChecked(): self._after_tts(self._start_wake_listener)

    def _select_pdf(self, number):
        if not self._document_selection or self._active_thread or self._voice_thread: return
        if not 1 <= number <= len(self._document_selection["labels"]):
            self.status.setToolTip("Choose one of the numbered PDFs."); return
        token = self._document_selection["token"]
        project = self._document_selection.get("kind") == "project"
        knowledge = self._document_selection.get('kind') == 'knowledge'
        self._document_selection = None
        self._selection_timer.stop(); self.pdf_choices.hide(); self.pdf_select_button.hide(); self.pdf_choices.clear()
        self.input.clear(); self._cancelled = False
        self._set_busy_controls(); self._set_status(Status.PROCESSING if project else Status.EXTRACTING_PDF)
        if knowledge:
            self._set_status(Status.PROCESSING)
            self._launch_command_worker(CommandWorker(self.executor, '[Selected indexed document]', knowledge_selection=(token, number)))
            return
        self._launch_command_worker(CommandWorker(self.executor, "[Selected project]" if project else "[Selected PDF]",
            project_selection=(token, number) if project else None, document_selection=None if project else (token, number)))

    def _cancel_confirmation(self, message="", resume=True):
        pending, self._confirmation = self._confirmation, None
        if pending and pending.get("kind") == "project": message = message.replace("Folder creation", "Project action")
        self._confirmation_timer.stop(); self.confirmation_panel.hide()
        from app.agent.executor import CommandExecutor
        if isinstance(self.executor, CommandExecutor):
            self.executor.confirmations.cancel()
            if self.executor.projects: self.executor.projects.cancel()
            if self.executor.knowledge: self.executor.knowledge.cancel()
        if pending:
            self.result_panel.setText(message); self._set_idle_controls()
            if resume and self.wake_toggle.isChecked(): self._after_tts(self._start_wake_listener)

    def _confirm_creation(self):
        if not self._confirmation or self._active_thread or self._voice_thread: return
        token = self._confirmation["token"]
        project_confirmation = (token, self._confirmation["hash"]) if self._confirmation.get("kind") == "project" else None
        knowledge_confirmation = (token, self._confirmation['hash']) if self._confirmation.get('kind') == 'knowledge' else None
        self._confirmation = None
        self._confirmation_timer.stop(); self.confirmation_panel.hide()
        self._cancelled = False
        self._set_busy_controls(); self._set_status(Status.PROCESSING)
        if knowledge_confirmation:
            self._launch_command_worker(CommandWorker(self.executor, '[Confirmed index action]', knowledge_confirmation=knowledge_confirmation))
            return
        self._launch_command_worker(CommandWorker(self.executor, "[Confirmed project]" if project_confirmation else "create_folder",
            confirmation_token=None if project_confirmation else token, project_confirmation=project_confirmation))

    def _project_selection_changed(self):
        item = self.project_selector.currentData()
        self.project_state.setText(f"Type: {item['type']} — profiles: {', '.join(item.get('profiles', [])) or 'none'}" if item else "No project selected")

    def _project_action(self, action):
        if self._active_thread or self._voice_thread or self._tts_pending: return
        if action == "profile":
            if self._wake_thread: self.status.setToolTip("Pause wake mode before editing a launch profile."); return
            from app.agent.executor import CommandExecutor
            if not isinstance(self.executor, CommandExecutor) or not self.executor.projects: return
            raw, accepted = QInputDialog.getMultiLineText(self, "Explicit launch profile", "Paste one profile JSON object (see README). Validation runs before saving:")
            if not accepted: return
            try:
                import json
                if len(raw) > 65536: raise ValueError()
                value = json.loads(raw)
            except ValueError:
                self.result_panel.setPlainText("Invalid profile JSON."); return
            self._cancel_confirmation(resume=False); self._cancel_pdf_selection(resume=False)
            self._cancelled = False; self._set_busy_controls()
            self._launch_command_worker(CommandWorker(self.executor, "[Save project profile]", project_profile=value))
            return
        if action in {"list", "running"}:
            text = "List my projects" if action == "list" else "Show running projects"
        else:
            item = self.project_selector.currentData()
            if not item: self.status.setToolTip("Refresh and select an approved project first."); return
            text = action + " project " + (item.get("profiles", [])[0] if len(item.get("profiles", [])) == 1 else item["name"])
        self.input.setText(text); self.execute_command()

    def _select_project_root(self):
        if self._active_thread or self._voice_thread or self._wake_thread: return
        from app.agent.executor import CommandExecutor
        if not isinstance(self.executor, CommandExecutor) or not self.executor.registry.filesystem: return
        self._cancel_confirmation(resume=False)
        self._cancel_pdf_selection(resume=False)
        path = QFileDialog.getExistingDirectory(self, "Select a local project folder to approve")
        if not path: return
        self._set_busy_controls(); self._cancelled = False
        self._launch_command_worker(ProjectRootWorker(self.executor.registry.filesystem.roots, path))

    def _show_level(self, level): self.audio_level.setValue(max(0, min(100, round(level * 500))))
    def _toggle_speech(self, enabled): self.tts.enabled = enabled
    def _set_status(self, status):
        self.status.setText(f"Status: {status.value}")
        self.status.setToolTip("")

    @Slot(str)
    def _recording_progress(self, message):
        self.status.setToolTip(message)

    def _test_microphone(self, device):
        if self._wake_thread is not None or self._voice_thread is not None or self._tts_pending:
            self.result_panel.setText("Stop listening before testing the microphone."); return
        success, message = self.recorder.test_device(device)
        if not success and self.microphone_settings: self.microphone_settings.refresh()
        self.result_panel.setText(message); self._set_status(Status.COMPLETED if success else Status.FAILED)

    def _set_microphone_sensitivity(self, value):
        if self.recorder is not None: self.recorder.sensitivity = value
        if self.wake_controller is not None: self.wake_controller.sensitivity = value

    def _load_history(self):
        try:
            for row in self.repository.recent(): self.history.addItem(f"{row['status']}: {row['original_command']} — {row['result_message']}")
        except Exception: logger.exception("Could not load command history")

    def closeEvent(self, event):
        from app.agent.executor import CommandExecutor
        if isinstance(self.executor, CommandExecutor) and self.executor.knowledge: self.executor.knowledge.close()
        self._project_output_timer.stop()
        self._wake_retry.stop()
        self._cancel_pdf_selection(resume=False)
        self._cancel_confirmation(resume=False)
        self._transition_generation += 1
        self._tts_pending = False
        self._cancelled = True; self._voice_cancel.set()
        if isinstance(self._active_worker, (CommandWorker, ProjectRootWorker)): self._active_worker.cancel_event.set()
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
        shutdown = getattr(self.wake_controller, "shutdown", None)
        if shutdown: shutdown()
        from app.agent.executor import CommandExecutor
        if isinstance(self.executor, CommandExecutor) and self.executor.projects: self.executor.projects.close()
        event.accept()
