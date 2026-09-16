"""Run the real application entry point with isolated settings and no audio hardware."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
from threading import enumerate as threads
from PySide6.QtCore import QTimer
import app.main as entry


def main():
    with TemporaryDirectory(prefix="voxpilot-startup-", dir=Path.cwd()) as temporary:
        base = Path(temporary)
        settings = replace(entry.Settings(), database_path=base / "history.sqlite3", approved_roots_path=base / "roots.json",
            voice_settings_path=base / "voice.json", project_profiles_path=base / "project-profiles.json", speech_enabled=False)
        entry.Settings = lambda: settings
        entry.load_project_env = lambda: None
        real_devices, real_window = entry.AudioDeviceService, entry.MainWindow
        backend = Mock(query_devices=Mock(return_value=[]), default=SimpleNamespace(device=(-1, -1)))
        entry.AudioDeviceService = lambda **kwargs: real_devices(backend=backend, **kwargs)
        captured = []
        def window(*args, **kwargs):
            result = real_window(*args, **kwargs); captured.append(result)
            QTimer.singleShot(100, result.close)
            return result
        entry.MainWindow = window
        result = entry.main()
        assert result == 0 and captured and not captured[0].isVisible()
        assert captured[0].executor.projects is not None
        assert not any(t.name.startswith("voxpilot-") for t in threads())
        backend.InputStream.assert_not_called(); backend.RawInputStream.assert_not_called()
        print("STARTUP_SMOKE_OK")
        return result


if __name__ == "__main__": raise SystemExit(main())
