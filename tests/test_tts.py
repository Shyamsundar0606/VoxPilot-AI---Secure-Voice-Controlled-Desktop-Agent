from threading import Event

from app.voice.tts import TextToSpeech


def test_tts_failure_is_contained():
    def broken(): raise RuntimeError("voice unavailable")
    tts = TextToSpeech(engine_factory=broken)
    tts._speak_safely("hello")
    assert tts.last_error == "RuntimeError"


def test_disabled_tts_does_nothing():
    assert TextToSpeech(enabled=False).speak("hello") is False


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
