from app.config import Settings, _transcription_timeout, _whisper_beam_size, load_project_env


def test_fixed_wake_phrase():
    from app.config import WAKE_PHRASE
    assert WAKE_PHRASE == "Hello"


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


def test_project_env_configures_cpu_before_settings_are_created(tmp_path, monkeypatch):
    monkeypatch.delenv("WHISPER_DEVICE", raising=False)
    monkeypatch.delenv("WHISPER_COMPUTE_TYPE", raising=False)
    env = tmp_path / ".env"
    env.write_text("WHISPER_DEVICE=cpu\nWHISPER_COMPUTE_TYPE=int8\n", encoding="utf-8")
    load_project_env(env)
    configured = Settings()
    assert configured.whisper_device == "cpu"
    assert configured.whisper_compute_type == "int8"


def test_project_env_does_not_replace_explicit_cuda(tmp_path, monkeypatch):
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    env = tmp_path / ".env"
    env.write_text("WHISPER_DEVICE=cpu\nWHISPER_COMPUTE_TYPE=int8\n", encoding="utf-8")
    load_project_env(env)
    assert Settings().whisper_device == "cuda"


def test_auto_device_cannot_create_an_implicit_cuda_model(monkeypatch):
    monkeypatch.setenv("WHISPER_DEVICE", "auto")
    assert Settings().whisper_device == "cpu"
