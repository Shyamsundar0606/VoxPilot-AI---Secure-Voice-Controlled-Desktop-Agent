from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models import AudioDevice, ResolvedAudioDevice

logger = logging.getLogger(__name__)


class DeviceResolutionError(RuntimeError):
    pass


class DeviceSelectionStore:
    """Persist stable identity; the numeric index is only a runtime hint."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, object] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError, TypeError):
            pass
        return None

    def save(self, device: AudioDevice | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        data = None if device is None else {
            "name": device.name,
            "host_api": device.host_api_name,
            "last_runtime_index": device.identifier,
        }
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(self.path)


class AudioDeviceService:
    def __init__(self, backend=None, store: DeviceSelectionStore | None = None, target_sample_rate: int = 16000):
        if backend is None:
            import sounddevice as backend
        self.backend, self.store, self.target_sample_rate = backend, store, target_sample_rate

    def diagnostics(self) -> list[AudioDevice]:
        """Return bounded diagnostics using original global PortAudio indices."""
        try:
            raw_devices = self.backend.query_devices()
            default = self._default_input()
            diagnostics = []
            for global_index, raw in enumerate(raw_devices):
                channels = int(raw.get("max_input_channels", 0))
                if channels <= 0:
                    continue
                host_name = self._host_api_name(raw.get("hostapi"))
                default_rate = float(raw.get("default_samplerate", 0.0) or 0.0)
                wdm_ks = "wdm-ks" in host_name.lower()
                supports_16k = False if wdm_ks else self._supports(global_index, self.target_sample_rate)
                supports_default = False
                if not wdm_ks and default_rate > 0:
                    supports_default = self._supports(global_index, default_rate)
                usable = not wdm_ks and (supports_16k or supports_default)
                reason = None
                if wdm_ks:
                    reason = "WDM-KS devices are excluded because they are commonly exclusive or unstable."
                elif not usable:
                    reason = "The device does not accept mono float32 input at 16 kHz or its default rate."
                diagnostics.append(AudioDevice(
                    identifier=global_index, name=str(raw.get("name", f"Device {global_index}")),
                    host_api_name=host_name, max_input_channels=channels,
                    default_sample_rate=default_rate, supports_16000=supports_16k,
                    supports_default_rate=supports_default, usable=usable,
                    reason=reason, is_default=global_index == default,
                ))
            return diagnostics
        except Exception as exc:
            logger.exception("Could not enumerate audio input devices")
            raise DeviceResolutionError(self._safe_reason(exc, "Could not enumerate Windows input devices.")) from exc

    def input_devices(self) -> list[AudioDevice]:
        try:
            return [device for device in self.diagnostics() if device.usable]
        except DeviceResolutionError:
            return []

    def selected_device(self, devices: list[AudioDevice]) -> int | None:
        saved = self.store.load() if self.store else None
        matched = self._match_saved(saved, devices)
        if matched:
            return matched.identifier
        default = next((device.identifier for device in devices if device.is_default), None)
        return default if default is not None else (devices[0].identifier if devices else None)

    def save_selected(self, identifier: int | None) -> None:
        if not self.store:
            return
        current = next((device for device in self.input_devices() if device.identifier == identifier), None)
        self.store.save(current)

    def resolve_for_recording(self, requested_index: int | None) -> ResolvedAudioDevice:
        devices = self.diagnostics()  # Always re-enumerate immediately before use.
        usable = [device for device in devices if device.usable]
        requested = next((device for device in devices if device.identifier == requested_index), None)
        if requested and requested.usable:
            return self._resolved(requested)

        saved = self.store.load() if self.store else None
        recovered = self._match_saved(saved, usable)
        if recovered:
            return self._resolved(recovered)

        default_index = self._default_input()
        default = next((device for device in usable if device.identifier == default_index), None)
        if default:
            return self._resolved(default)

        if requested is None and requested_index is not None:
            reason = f"Selected microphone index {requested_index} is stale or disconnected."
        elif requested and requested.reason:
            reason = requested.reason
        else:
            reason = "No usable input microphone is available."
        available = ", ".join(f"{d.name} [{d.host_api_name}]" for d in usable)
        if available:
            reason += f" Usable microphones: {available}."
        raise DeviceResolutionError(reason)

    def test_device(self, identifier: int | None) -> tuple[bool, str]:
        try:
            resolved = self.resolve_for_recording(identifier)
            rate_note = "16 kHz" if not resolved.requires_resampling else f"{resolved.sample_rate} Hz with safe resampling to 16 kHz"
            return True, f"{resolved.name} [{resolved.host_api_name}] is available at {rate_note}."
        except DeviceResolutionError as exc:
            return False, str(exc)

    def _resolved(self, device: AudioDevice) -> ResolvedAudioDevice:
        rate = self.target_sample_rate if device.supports_16000 else round(device.default_sample_rate)
        return ResolvedAudioDevice(identifier=device.identifier, name=device.name, host_api_name=device.host_api_name, sample_rate=rate, requires_resampling=rate != self.target_sample_rate)

    @staticmethod
    def _match_saved(saved: dict[str, object] | None, devices: list[AudioDevice]) -> AudioDevice | None:
        if not saved:
            return None
        name, host = saved.get("name"), saved.get("host_api")
        if name and host:
            return next((device for device in devices if device.name == name and device.host_api_name == host), None)
        # Legacy numeric-only settings are a temporary hint, never a stable identity.
        legacy = saved.get("input_device")
        return next((device for device in devices if device.identifier == legacy), None)

    def _supports(self, index: int, sample_rate: float) -> bool:
        try:
            self.backend.check_input_settings(device=index, channels=1, samplerate=sample_rate, dtype="float32")
            return True
        except Exception:
            return False

    def _host_api_name(self, index) -> str:
        try:
            if index is None:
                return "Unknown"
            return str(self.backend.query_hostapis(int(index))["name"])
        except Exception:
            return "Unknown"

    def _default_input(self) -> int | None:
        try:
            value = self.backend.default.device
            try:
                result = value[0]
            except (TypeError, IndexError):
                result = value
            return int(result) if int(result) >= 0 else None
        except (AttributeError, IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _safe_reason(exc: Exception, fallback: str) -> str:
        detail = " ".join(str(exc).split())[:240]
        return f"{fallback} {detail}".strip()
