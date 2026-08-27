from types import SimpleNamespace

import pytest

from app.models import AudioDevice
from app.voice.audio_devices import AudioDeviceService, DeviceResolutionError, DeviceSelectionStore


class FakeBackend:
    def __init__(self, devices=None, supported=None, default=2, hostapis=None):
        self.devices = devices or [
            {"name": "Speakers", "max_input_channels": 0, "default_samplerate": 48000, "hostapi": 0},
            {"name": "Broken mic", "max_input_channels": 1, "default_samplerate": 44100, "hostapi": 0},
            {"name": "Realtek Array", "max_input_channels": 2, "default_samplerate": 48000, "hostapi": 0},
        ]
        self.supported = supported if supported is not None else {(2, 16000), (2, 48000)}
        self.default = SimpleNamespace(device=(default, 0))
        self.hostapis = hostapis or {0: {"name": "Windows WASAPI"}, 1: {"name": "Windows WDM-KS"}}
        self.checked = []

    def query_devices(self): return self.devices
    def query_hostapis(self, index): return self.hostapis[index]
    def check_input_settings(self, **kwargs):
        self.checked.append(kwargs)
        if (kwargs["device"], round(kwargs["samplerate"])) not in self.supported:
            raise RuntimeError("unsupported")


def test_filtered_position_differs_from_preserved_global_index():
    devices = AudioDeviceService(FakeBackend()).input_devices()
    assert len(devices) == 1
    assert devices[0].identifier == 2


def test_diagnostic_function_returns_required_fields():
    diagnostic = AudioDeviceService(FakeBackend()).diagnostics()[1]
    assert diagnostic.identifier == 2
    assert diagnostic.host_api_name == "Windows WASAPI"
    assert diagnostic.max_input_channels == 2
    assert diagnostic.default_sample_rate == 48000
    assert diagnostic.supports_16000 and diagnostic.supports_default_rate


def test_stale_persisted_index_recovers_by_name_and_host_api(tmp_path):
    store = DeviceSelectionStore(tmp_path / "voice.json")
    store.save(AudioDevice(identifier=99, name="Realtek Array", host_api_name="Windows WASAPI"))
    service = AudioDeviceService(FakeBackend(), store)
    assert service.resolve_for_recording(99).identifier == 2


def test_default_device_fallback_for_stale_selection():
    service = AudioDeviceService(FakeBackend(default=2))
    assert service.resolve_for_recording(99).identifier == 2


def test_unsupported_16khz_falls_back_to_default_rate():
    backend = FakeBackend(supported={(2, 48000)})
    resolved = AudioDeviceService(backend).resolve_for_recording(2)
    assert resolved.sample_rate == 48000 and resolved.requires_resampling


def test_invalid_device_reports_safe_reason():
    with pytest.raises(DeviceResolutionError, match="stale|No usable"):
        AudioDeviceService(FakeBackend(supported=set(), default=-1)).resolve_for_recording(99)


def test_disconnected_device_falls_back_to_current_default(tmp_path):
    store = DeviceSelectionStore(tmp_path / "voice.json")
    store.save(AudioDevice(identifier=7, name="Disconnected USB", host_api_name="Windows WASAPI"))
    assert AudioDeviceService(FakeBackend(default=2), store).resolve_for_recording(7).identifier == 2


def test_wdm_ks_device_is_rejected():
    backend = FakeBackend(
        devices=[{"name": "KS microphone", "max_input_channels": 2, "default_samplerate": 48000, "hostapi": 1}],
        supported={(0, 16000), (0, 48000)}, default=0,
    )
    diagnostic = AudioDeviceService(backend).diagnostics()[0]
    assert not diagnostic.usable and "WDM-KS" in diagnostic.reason
    assert AudioDeviceService(backend).input_devices() == []


def test_persistence_uses_name_and_host_api(tmp_path):
    store = DeviceSelectionStore(tmp_path / "voice.json")
    service = AudioDeviceService(FakeBackend(), store); service.save_selected(2)
    saved = store.load()
    assert saved["name"] == "Realtek Array" and saved["host_api"] == "Windows WASAPI"
