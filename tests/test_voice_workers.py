from threading import Event
from unittest.mock import Mock

from app.models import RecordingResult, TranscriptionResult
from app.ui.workers import RecordingWorker, TranscriptionWorker


def test_recording_worker_success_signal():
    recorder = Mock(); recorder.record.return_value = RecordingResult(success=True, audio=[1], duration=1, speech_duration=1)
    worker = RecordingWorker(recorder, 1, Event()); emitted = []; worker.finished.connect(emitted.append); worker.run()
    assert emitted[0].success


def test_recording_worker_failure_signal():
    recorder = Mock(); recorder.record.side_effect = RuntimeError("broken")
    worker = RecordingWorker(recorder, 1, Event()); emitted = []; worker.finished.connect(emitted.append); worker.run()
    assert not emitted[0].success and emitted[0].error_code == "worker_error"


def test_transcription_worker_success_signal():
    transcriber = Mock(); transcriber.transcribe.return_value = TranscriptionResult(success=True, text="Help", model_used="base.en")
    worker = TranscriptionWorker(transcriber, Mock(), Event()); emitted = []; worker.finished.connect(emitted.append); worker.run()
    assert emitted[0].success


def test_transcription_worker_cancellation_signal():
    transcriber = Mock(); transcriber.transcribe.return_value = TranscriptionResult(success=False, cancelled=True, error_code="cancelled", message="Cancelled", model_used="base.en")
    worker = TranscriptionWorker(transcriber, Mock(), Event()); emitted = []; worker.finished.connect(emitted.append); worker.run()
    assert emitted[0].cancelled
