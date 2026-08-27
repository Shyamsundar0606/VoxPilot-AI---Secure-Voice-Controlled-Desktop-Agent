import logging
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot

from app.models import ExecutionResult, Status

logger = logging.getLogger(__name__)


class CommandWorker(QObject):
    finished = Signal(object)

    def __init__(self, executor, command: str):
        super().__init__()
        self.executor, self.command = executor, command

    @Slot()
    def run(self):
        result = None
        try:
            if QThread.currentThread().isInterruptionRequested():
                result = self._cancelled_result()
            else:
                result = self.executor.execute(self.command)
        except Exception as exc:
            logger.exception("Unhandled command worker failure")
            result = ExecutionResult(
                original_command=self.command,
                normalized_command=" ".join(self.command.lower().split()),
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
            original_command=self.command,
            normalized_command=" ".join(self.command.lower().split()),
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

    def __init__(self, transcriber, recording, cancel_event: Event):
        super().__init__()
        self.transcriber, self.recording, self.cancel_event = transcriber, recording, cancel_event

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
            self.finished.emit(result)
