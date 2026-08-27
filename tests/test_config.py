from app.config import _transcription_timeout, _whisper_beam_size


def test_cpu_beam_size_and_timeout_defaults(monkeypatch):
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.delenv("WHISPER_BEAM_SIZE", raising=False)
    monkeypatch.delenv("VOXPILOT_TRANSCRIPTION_TIMEOUT", raising=False)
    assert _whisper_beam_size() == 1
    assert _transcription_timeout() == 180.0


def test_explicit_cuda_configuration_is_preserved(monkeypatch):
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    monkeypatch.setenv("WHISPER_BEAM_SIZE", "4")
    monkeypatch.setenv("VOXPILOT_TRANSCRIPTION_TIMEOUT", "75")
    assert _whisper_beam_size() == 4
    assert _transcription_timeout() == 75.0
