from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.models import ToolResult
from app.security.policy import ALLOWED_APPLICATIONS

logger = logging.getLogger(__name__)

DISPLAY_NAMES = {
    "chrome": "Chrome", "spotify": "Spotify", "settings": "Windows Settings",
    "notepad": "Notepad", "word": "Microsoft Word", "calculator": "Calculator",
    "vscode": "VS Code", "file_explorer": "File Explorer",
}


@dataclass(frozen=True)
class ApplicationSpec:
    executable_names: tuple[str, ...]
    registry_names: tuple[str, ...] = ()
    relative_paths: tuple[tuple[str, str], ...] = ()
    system_relative_path: str | None = None
    uri: str | None = None


APPLICATION_SPECS: dict[str, ApplicationSpec] = {
    "chrome": ApplicationSpec(
        ("chrome.exe",), ("chrome.exe",),
        (("ProgramFiles", r"Google\Chrome\Application\chrome.exe"),
         ("ProgramFiles(x86)", r"Google\Chrome\Application\chrome.exe"),
         ("LOCALAPPDATA", r"Google\Chrome\Application\chrome.exe")),
    ),
    "spotify": ApplicationSpec(
        ("Spotify.exe",), ("Spotify.exe",),
        (("APPDATA", r"Spotify\Spotify.exe"),), uri="spotify:",
    ),
    "settings": ApplicationSpec(("explorer.exe",), system_relative_path="explorer.exe", uri="ms-settings:"),
    "notepad": ApplicationSpec(("notepad.exe",), ("notepad.exe",), system_relative_path=r"System32\notepad.exe"),
    "word": ApplicationSpec(
        ("WINWORD.EXE",), ("WINWORD.EXE",),
        tuple(
            (root, relative)
            for root in ("ProgramFiles", "ProgramFiles(x86)")
            for relative in (
                r"Microsoft Office\root\Office16\WINWORD.EXE",
                r"Microsoft Office\Office16\WINWORD.EXE",
                r"Microsoft Office\Office15\WINWORD.EXE",
            )
        ),
    ),
    "calculator": ApplicationSpec(("calc.exe",), system_relative_path=r"System32\calc.exe", uri="calculator:"),
    "vscode": ApplicationSpec(
        ("Code.exe",), ("Code.exe",),
        (("LOCALAPPDATA", r"Programs\Microsoft VS Code\Code.exe"),
         ("ProgramFiles", r"Microsoft VS Code\Code.exe"),
         ("ProgramFiles(x86)", r"Microsoft VS Code\Code.exe")),
    ),
    "file_explorer": ApplicationSpec(("explorer.exe",), system_relative_path="explorer.exe"),
}


def _windows_app_path(executable_name: str) -> str | None:
    """Read only the fixed Windows App Paths keys for an approved executable."""
    try:
        import winreg
    except ImportError:
        return None
    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}"
    access_modes = (winreg.KEY_READ, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0))
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for access in access_modes:
            try:
                with winreg.OpenKey(hive, key_path, 0, access) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    return str(value).strip('"')
            except OSError:
                continue
    return None


class ApprovedApplicationResolver:
    def __init__(
        self,
        which: Callable[[str], str | None] = shutil.which,
        registry_lookup: Callable[[str], str | None] = _windows_app_path,
        environment: Mapping[str, str] | None = None,
        is_file: Callable[[Path], bool] | None = None,
    ):
        self.which = which
        self.registry_lookup = registry_lookup
        self.environment = os.environ if environment is None else environment
        self.is_file = is_file or Path.is_file

    def resolve(self, application: str) -> list[str] | None:
        if application not in ALLOWED_APPLICATIONS:
            return None
        spec = APPLICATION_SPECS.get(application)
        if spec is None:
            return None

        executable = self._resolve_executable(spec)
        if executable is not None:
            # Explorer is the fixed Windows handler for the Settings URI.
            if application == "settings" and spec.uri:
                return [str(executable), spec.uri]
            return [str(executable)]

        # Store-app URI activation uses only a validated system explorer executable.
        if spec.uri:
            explorer = self._resolve_system_explorer()
            if explorer is not None:
                return [str(explorer), spec.uri]
        return None

    def _resolve_executable(self, spec: ApplicationSpec) -> Path | None:
        for name in spec.executable_names:
            candidate = self.which(name)
            if candidate and self._valid_file(candidate):
                return Path(candidate)
        for name in spec.registry_names:
            candidate = self.registry_lookup(name)
            if candidate and self._valid_file(candidate):
                return Path(candidate)
        for root_name, relative in spec.relative_paths:
            root = self.environment.get(root_name)
            if root:
                candidate = Path(root) / relative
                if self._valid_file(candidate):
                    return candidate
        if spec.system_relative_path:
            windows_root = self.environment.get("SystemRoot") or self.environment.get("WINDIR")
            if windows_root:
                candidate = Path(windows_root) / spec.system_relative_path
                if self._valid_file(candidate):
                    return candidate
        return None

    def _resolve_system_explorer(self) -> Path | None:
        candidate = self.which("explorer.exe")
        if candidate and self._valid_file(candidate):
            return Path(candidate)
        windows_root = self.environment.get("SystemRoot") or self.environment.get("WINDIR")
        if windows_root:
            candidate_path = Path(windows_root) / "explorer.exe"
            if self._valid_file(candidate_path):
                return candidate_path
            candidate_path = Path(windows_root) / "System32" / "explorer.exe"
            if self._valid_file(candidate_path):
                return candidate_path
        return None

    def _valid_file(self, candidate: str | Path) -> bool:
        try:
            return bool(self.is_file(Path(candidate)))
        except OSError:
            return False


class ApplicationTools:
    def __init__(self, launcher: Callable[..., object] = subprocess.Popen, resolver: ApprovedApplicationResolver | None = None):
        self.launcher = launcher
        self.resolver = resolver or ApprovedApplicationResolver()

    def open_application(self, application: str) -> ToolResult:
        if application not in ALLOWED_APPLICATIONS or application not in APPLICATION_SPECS:
            return ToolResult(success=False, message="That application is not available in the approved application list.", error="Application not allowlisted")
        command = self.resolver.resolve(application)
        if command is None:
            return ToolResult(success=False, message=f"{DISPLAY_NAMES[application]} could not be found or opened.", error="Application not found")
        try:
            self.launcher(command, shell=False, close_fds=os.name != "nt")
            return ToolResult(success=True, message=f"{DISPLAY_NAMES[application]} is now open.")
        except (FileNotFoundError, OSError) as exc:
            logger.exception("Approved application failed to launch: %s", application)
            return ToolResult(success=False, message=f"{DISPLAY_NAMES[application]} could not be found or opened.", error=type(exc).__name__)
