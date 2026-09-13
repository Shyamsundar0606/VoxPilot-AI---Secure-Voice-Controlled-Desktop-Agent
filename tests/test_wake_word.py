"""Streaming wake behavior with synthetic PCM; never opens a real microphone."""
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
import pytest

from app.models import WakeWordResult
from app.ui.workers import WakeWordWorker
from app.voice.wake_word import WakeWordController, is_wake_phrase, normalize_wake_text
from app.voice.recorder import AudioRecorder
from app.voice.vosk_decoder import WakeDecoderError


def controller_result(text="Hello", rate=16000, sensitivity="normal", frames=2):
    cancel = Event()
    settings = SimpleNamespace(wake_phrase="Hello", wake_engine="vosk", vosk_sample_rate=16000,
        vosk_model_path="unused", microphone_sensitivity=sensitivity)
    service = Mock(resolve_for_recording=Mock(return_value=SimpleNamespace(identifier=7, sample_rate=rate)))
    stream = Mock(); stream.active = False
    buffers = []
    def open_stream(**kwargs):
        stream.options = kwargs
        return stream
    def enter():
        stream.active = True
        for _ in range(frames):
            stream.options['callback'](np.full(round(rate*.05), 2000, dtype=np.int16).tobytes(), round(rate*.05), None, False)
        return stream
    stream.__enter__ = Mock(side_effect=enter)
    stream.__exit__ = Mock(side_effect=lambda *_: setattr(stream, 'active', False))
    backend = Mock(RawInputStream=Mock(side_effect=open_stream))
    def feed(pcm, event):
        assert stream.active
        buffers.append(pcm)
        if not is_wake_phrase(text): event.set()
        return text
    decoder = Mock(feed=Mock(side_effect=feed))
    controller = WakeWordController(settings, service, backend=backend, decoder=decoder)
    return controller, cancel, stream, buffers


@pytest.mark.parametrize('text', ['Hello', 'hello', 'HELLO!', 'Hello.', '  hello  ', '\t HELLO!\n'])
def test_wake_phrase_detection_and_normalization(text):
    assert is_wake_phrase(text) and normalize_wake_text(text) == 'hello'
    controller, cancel, stream, buffers = controller_result(text)
    assert controller.listen_once(7, cancel).detected
    assert not stream.active and not AudioRecorder._microphone_lock.locked()
    assert buffers and not any(buffers[0])


@pytest.mark.parametrize('text', ['Hello Google', 'Hey Shyam', 'Open Chrome', '', '[unk]', 'hello [unk]', 'hello hello', 'please hello'])
def test_non_wake_speech_is_ignored(text):
    controller, cancel, _, _ = controller_result(text)
    assert not controller.listen_once(7, cancel).detected


def test_precancelled_does_not_open_microphone_or_decoder():
    controller, cancel, _, _ = controller_result(); cancel.set()
    assert controller.listen_once(7, cancel).cancelled
    controller.backend.RawInputStream.assert_not_called()
    controller.decoder.start.assert_not_called()


def test_exception_clears_audio_and_closes_stream():
    controller, cancel, stream, buffers = controller_result()
    def fail(pcm, event):
        buffers.append(pcm); raise WakeDecoderError('decoder_failed')
    controller.decoder.feed.side_effect = fail
    assert controller.listen_once(7, cancel).error_code == 'decoder_failed'
    assert not stream.active and not any(buffers[0])
    assert not AudioRecorder._microphone_lock.locked()
    controller.decoder.reset.assert_called_once()


def test_microphone_mutex_blocks_wake_when_command_owns_it():
    controller, cancel, _, _ = controller_result()
    with AudioRecorder._microphone_lock:
        assert controller.listen_once(7, cancel).error_code == 'microphone_busy'
    controller.backend.RawInputStream.assert_not_called()


def test_command_cannot_open_while_vosk_owns_microphone():
    controller, cancel, _, _ = controller_result()
    def feed(*_):
        recorder = AudioRecorder(SimpleNamespace(), backend=Mock(), device_service=Mock())
        assert recorder.record(7, Event()).error_code == 'microphone_busy'
        assert not controller._session_lock.acquire(blocking=False)
        return 'hello'
    controller.decoder.feed.side_effect = feed
    assert controller.listen_once(7, cancel).detected


def test_duplicate_controller_session_rejected():
    controller, cancel, _, _ = controller_result()
    with controller._session_lock:
        assert controller.listen_once(7, cancel).error_code == 'microphone_busy'
    controller.decoder.start.assert_not_called()


def test_disconnection_then_recovery_re_resolves_selected_device():
    controller, cancel, stream, _ = controller_result()
    original = stream.__enter__.side_effect
    stream.__enter__.side_effect = OSError('private driver error')
    first = controller.listen_once(2, cancel)
    assert first.error_code == 'invalid_device' and 'private driver' not in first.message
    stream.__enter__.side_effect = original
    assert controller.listen_once(2, cancel).detected
    assert controller.device_service.resolve_for_recording.call_count == 2
    assert stream.options['device'] == 7


def test_worker_activation_only_after_stream_is_closed():
    controller, cancel, stream, _ = controller_result()
    worker = WakeWordWorker(controller, 7, cancel)
    events = []
    def activation(text):
        assert not stream.active and not AudioRecorder._microphone_lock.locked()
        events.append(text)
    worker.activation.connect(activation)
    worker.finished.connect(lambda: events.append('finished'))
    worker.run()
    assert events == ['Hello', 'finished']
    assert not hasattr(controller, 'transcriber') and not hasattr(controller, 'executor')


def test_late_detected_result_after_cancel_is_ignored():
    cancel = Event()
    controller = Mock()
    controller.listen_once.side_effect = lambda *_: (cancel.set(), WakeWordResult(detected=True))[1]
    worker = WakeWordWorker(controller, 7, cancel)
    detected, finished = Mock(), Mock()
    worker.activation.connect(detected); worker.finished.connect(finished); worker.run()
    detected.assert_not_called(); finished.assert_called_once()


def test_missing_model_is_setup_failure():
    controller, cancel, _, _ = controller_result()
    controller.decoder.start.side_effect = WakeDecoderError('missing_model')
    worker = WakeWordWorker(controller, 7, cancel)
    failed, activated = Mock(), Mock()
    worker.setup_failed.connect(failed); worker.activation.connect(activated); worker.run()
    assert 'VOSK_MODEL_PATH' in failed.call_args.args[0]
    activated.assert_not_called(); controller.backend.RawInputStream.assert_not_called()


@pytest.mark.parametrize('rate', [16000, 44100, 48000])
def test_pcm_format_and_resampling(rate):
    controller, cancel, stream, _ = controller_result(rate=rate)
    lengths = []
    controller.decoder.feed.side_effect = lambda pcm, event: (lengths.append(len(pcm)), 'hello')[1]
    assert controller.listen_once(7, cancel).detected
    assert lengths == [1600]
    assert stream.options['channels'] == 1 and stream.options['dtype'] == 'int16'
    assert stream.options['blocksize'] == round(rate*.05)


def test_sensitivity_reused_as_bounded_gain():
    controller, cancel, _, _ = controller_result(sensitivity='high')
    levels = []
    controller.decoder.feed.side_effect = lambda pcm, event: (levels.append(np.frombuffer(pcm, dtype='<i2').max()), 'hello')[1]
    assert controller.listen_once(7, cancel).detected
    assert levels == [4000]


def test_queue_overflow_fails_without_activation():
    controller, cancel, _, _ = controller_result(frames=25)
    assert controller.listen_once(7, cancel).error_code == 'invalid_device'
    controller.decoder.feed.assert_not_called()
    assert not AudioRecorder._microphone_lock.locked()


def test_queued_buffers_are_cleared_on_activation(monkeypatch):
    import app.voice.wake_word as module
    from queue import Queue
    queued = []
    class InspectQueue(Queue):
        def put_nowait(self, item):
            queued.append(item)
            return super().put_nowait(item)
    monkeypatch.setattr(module, 'Queue', InspectQueue)
    controller, cancel, _, _ = controller_result(frames=10)
    assert controller.listen_once(7, cancel).detected
    assert len(queued) == 10 and all(not any(frame) for frame in queued)


def test_callback_status_discards_utterance():
    controller, cancel, stream, _ = controller_result()
    stream.__enter__.side_effect = lambda: stream.options['callback'](bytes(1600), 800, None, True)
    assert controller.listen_once(7, cancel).error_code == 'invalid_device'
    controller.decoder.feed.assert_not_called()


def test_stop_while_waiting_for_audio_closes_stream():
    from threading import Thread
    from time import monotonic, sleep
    controller, cancel, stream, _ = controller_result(frames=0)
    results = []
    thread = Thread(target=lambda: results.append(controller.listen_once(7, cancel)))
    thread.start()
    try:
        deadline = monotonic() + 1
        while not stream.active and monotonic() < deadline: sleep(.001)
        assert stream.active
        cancel.set(); thread.join(2)
        assert not thread.is_alive() and results[0].cancelled
        assert not stream.active and not AudioRecorder._microphone_lock.locked()
    finally: cancel.set(); thread.join(2)


@pytest.mark.parametrize('engine,rate,phrase', [('whisper', 16000, 'hello'), ('vosk', 48000, 'hello'), ('vosk', 16000, ''), ('vosk', 16000, '[unk]')])
def test_invalid_configuration_never_opens_stream(engine, rate, phrase):
    controller, cancel, _, _ = controller_result()
    controller.engine, controller.sample_rate, controller.phrase = engine, rate, phrase
    assert controller.listen_once(7, cancel).error_code == 'invalid_configuration'
    controller.backend.RawInputStream.assert_not_called()
