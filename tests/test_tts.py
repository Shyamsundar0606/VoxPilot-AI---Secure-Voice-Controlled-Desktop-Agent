from threading import Event

from app.voice.tts import TextToSpeech


def test_tts_failure_is_contained():
    def broken(): raise RuntimeError("voice unavailable")
    tts = TextToSpeech(engine_factory=broken)
    tts._speak_safely("hello")
    assert tts.last_error == "RuntimeError"


def test_disabled_tts_does_nothing():
    assert TextToSpeech(enabled=False).speak("hello") is False


def test_busy_state_clears_after_queued_speech():
    class Engine:
        def say(self, _text): pass
        def runAndWait(self): pass
    tts = TextToSpeech(engine_factory=Engine, timeout=0.1)
    assert tts.speak("hello") and tts.is_busy()
    tts._queue.join()
    assert not tts.is_busy()


def test_tts_exception_does_not_stop_queue():
    def broken(): raise RuntimeError("voice unavailable")
    tts = TextToSpeech(engine_factory=broken, timeout=0.1)
    assert tts.speak("hello")
    tts._queue.join()
    assert tts.last_error == "RuntimeError"


def test_tts_timeout_is_bounded():
    release = Event()

    class HangingEngine:
        def say(self, _text): pass
        def runAndWait(self): release.wait(2)

    tts = TextToSpeech(engine_factory=HangingEngine, timeout=0.02)
    assert tts.speak("hello")
    tts._queue.join()
    assert tts.last_error == "TimeoutError"
    release.set()


def test_shutdown_joins_queue_worker():
    tts = TextToSpeech(enabled=False)
    tts.shutdown()
    assert not tts._worker.is_alive()
    assert not tts.is_busy()
    assert not tts.speak("after close")


def test_native_timeout_terminates_speech_before_clearing_busy(monkeypatch):
    from unittest.mock import Mock
    import app.voice.tts as module
    context = Mock()
    receiver, sender = Mock(), Mock()
    context.Pipe.return_value = (receiver, sender)
    process = context.Process.return_value
    process.is_alive.side_effect = [True, False]
    monkeypatch.setattr(module, "get_context", lambda mode: context)
    tts = TextToSpeech(timeout=0.01)
    tts.speak("test")
    tts._queue.join()
    assert tts.last_error == "TimeoutError"
    assert not tts.is_busy()
    process.terminate.assert_called_once()
    assert process.join.call_count == 2
    tts.shutdown()
