from app.config import Settings, _transcription_timeout, _whisper_beam_size, load_project_env


def test_default_wake_phrase():
    from app.config import WAKE_PHRASE
    assert WAKE_PHRASE == "Hello"


def test_vosk_configuration_and_shared_phrase_normalization(monkeypatch):
    from app.voice.wake_word import is_wake_phrase
    monkeypatch.setenv("VOXPILOT_WAKE_ENGINE", "vosk")
    monkeypatch.setenv("VOXPILOT_WAKE_PHRASE", "  Hello Pilot  ")
    monkeypatch.setenv("VOSK_MODEL_PATH", "models/local-test")
    monkeypatch.setenv("VOSK_SAMPLE_RATE", "16000")
    settings = Settings()
    assert settings.wake_engine == "vosk" and settings.vosk_sample_rate == 16000
    assert settings.wake_phrase == "Hello Pilot"
    assert settings.vosk_model_path.as_posix() == "models/local-test"
    assert is_wake_phrase("HELLO PILOT!") and not is_wake_phrase("hello")
    from unittest.mock import Mock
    from app.agent.executor import CommandExecutor
    router, planner = Mock(), Mock()
    result = CommandExecutor(router=router, planner=planner).execute("HELLO PILOT!")
    assert not result.store_history
    router.route.assert_not_called(); planner.plan.assert_not_called()


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
