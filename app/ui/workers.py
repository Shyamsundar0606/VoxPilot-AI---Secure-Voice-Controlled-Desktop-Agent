import logging
from enum import StrEnum
from weakref import ref
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot

from app.models import ExecutionResult, Status
from app.agent.executor import CommandExecutor

logger = logging.getLogger(__name__)


class VoiceSource(StrEnum):
    WAKE = "wake_detection"
    WAKE_COMMAND = "wake_command"
    MANUAL = "manual"


class VoiceSignalRelay(QObject):
    """GUI-thread receiver retaining session identity after worker deletion."""
    def __init__(self, window, worker, wake=False):
        super().__init__(window)
        self._window, self.worker, self.wake = ref(window), worker, wake

    @property
    def window(self):
        return self._window()

    def current(self):
        if self.window is None: return False
        return self.worker is (self.window._wake_worker if self.wake else self.window._voice_worker)

    @Slot(str)
    def activation(self, text):
        if self.current(): self.window._wake_activation(text, self.worker)

    @Slot(object)
    def recording(self, result):
        if self.current(): self.window._store_voice_result(result, self.worker)
        else: self.window._clear_audio(result)

    @Slot(object, str)
    def transcription(self, result, source):
        if self.current(): self.window._store_transcription_result(result, source, self.worker)

    @Slot(str)
    def state(self, state):
        if self.current(): self.window._wake_state_changed(state, self.worker)

    @Slot(float)
    def level(self, level):
        if self.current() and not self.window._wake_cancel.is_set(): self.window._show_level(level)

    @Slot(str)
    def failure(self, message):
        if self.current() and not self.window._wake_cancel.is_set(): self.window._wake_failure(message)


class CommandWorker(QObject):
    finished = Signal(object)

    def __init__(self, executor, command: str):
        super().__init__()
        self.executor, self.command = executor, command
        self.cancel_event = Event()

    @Slot()
    def run(self):
        result = None
        try:
            if self.cancel_event.is_set() or QThread.currentThread().isInterruptionRequested():
                result = self._cancelled_result()
            else:
                if isinstance(self.executor, CommandExecutor):
                    result = self.executor.execute(self.command, self.cancel_event)
                else:
                    result = self.executor.execute(self.command)
        except Exception as exc:
            logger.error("Unhandled command worker failure: %s", type(exc).__name__)
            result = ExecutionResult(
                original_command="[Command failed]",
                normalized_command="",
                selected_tool=None,
                status=Status.FAILED,
                result_message="The command could not be completed safely.",
                error_message=type(exc).__name__,
            )
        finally:
            if result is None:
                result = self._cancelled_result()
            self.finished.emit(result)

    def _cancelled_result(self):
        return ExecutionResult(
            original_command="[Cancelled request]",
            normalized_command="",
            selected_tool=None,
            status=Status.FAILED,
            result_message="The pending command was cancelled.",
            error_message="Cancelled",
        )


class RecordingWorker(QObject):
    level_changed = Signal(float)
    status_changed = Signal(str)
    finished = Signal(object)

    def __init__(self, recorder, device: int | None, stop_event: Event):
        super().__init__()
        self.recorder, self.device, self.stop_event = recorder, device, stop_event

    @Slot()
    def run(self):
        result = None
        try:
            result = self.recorder.record(self.device, self.stop_event, self.level_changed.emit, self.status_changed.emit)
        except Exception as exc:
            logger.exception("Unhandled recording worker failure")
            from app.models import RecordingResult
            result = RecordingResult(success=False, error_code="worker_error", message="Microphone recording failed safely.")
        finally:
            self.finished.emit(result)


class TranscriptionWorker(QObject):
    finished = Signal(object)
    result_ready = Signal(object, str)

    def __init__(self, transcriber, recording, cancel_event: Event, source=VoiceSource.MANUAL):
        super().__init__()
        self.transcriber, self.recording, self.cancel_event = transcriber, recording, cancel_event
        self.source = source

    @Slot()
    def run(self):
        result = None
        try:
            result = self.transcriber.transcribe(self.recording, self.cancel_event)
        except Exception:
            logger.exception("Unhandled transcription worker failure")
            from app.models import TranscriptionResult
            result = TranscriptionResult(success=False, model_used="unknown", error_code="worker_error", message="Transcription failed safely.")
        finally:
            self.result_ready.emit(result, self.source)
            self.finished.emit(result)


class WakeWordWorker(QObject):
    activation = Signal(str)
    state_changed = Signal(str)
    level_changed = Signal(float)
    detected = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, controller, device, cancel_event):
        super().__init__(); self.controller, self.device, self.cancel_event = controller, device, cancel_event

    @Slot()
    def run(self):
        try:
            while not self.cancel_event.is_set():
                self.state_changed.emit("Wake-word listening")
                result = self.controller.listen_once(self.device, self.cancel_event, self.level_changed.emit, self.state_changed.emit)
                if result.cancelled: break
                if result.error_code:
                    self.failed.emit(result.message); break
                if result.detected:
                    from app.config import WAKE_PHRASE
                    self.activation.emit(WAKE_PHRASE)
                    self.detected.emit(); break
        except Exception:
            logger.exception("Wake-word listener failed")
            self.failed.emit("Wake-word listening failed safely.")
        finally:
            self.finished.emit()
