import json
from pathlib import Path
from threading import RLock

from app.filesystem.platform import WindowsFolders
from app.security.filesystem_policy import FilePolicyError, check_path_chain, safe_relative, safe_component, RootArgs, KNOWN_ROOTS


class ApprovedRoots:
    def __init__(self, settings_path=None, platform=None, roots=None):
        self.platform = platform or WindowsFolders()
        self.settings_path = Path(settings_path) if settings_path else None
        self._roots = {key: Path(value) for key, value in roots.items()} if roots is not None else None
        self._lock = RLock()

    def configuration(self):
        """Export configuration without resolving folders on the caller thread."""
        with self._lock:
            return (dict(self._roots) if self._roots is not None else None, self.settings_path)

    def snapshot(self):
        with self._lock:
            if self._roots is None:
                self._roots = self.platform.known_roots()
                if self.settings_path and self.settings_path.exists():
                    try:
                        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
                        for key, value in saved.get("project_roots", {}).items():
                            RootArgs(root=key)
                            if key not in KNOWN_ROOTS: self._roots[key] = Path(value)
                    except (ValueError, TypeError, AttributeError):
                        pass
            return dict(self._roots)

    def _approved_root(self, path):
        path = Path(path)
        if not path.is_absolute() or str(path).startswith(("\\\\", "//")) or path == Path(path.anchor):
            raise FilePolicyError("Drive roots and network locations are not approved.")
        if not self.platform.fixed_drive(path):
            raise FilePolicyError("Only local fixed drives are approved.")
        for part in path.parts[1:]: safe_component(part)
        check_path_chain(path)
        resolved = path.resolve(strict=True)
        check_path_chain(resolved)
        if not resolved.is_dir(): raise FilePolicyError("Approved location is not a folder.")
        # Disallow approving a broad ancestor of a sensitive location (e.g. user profile).
        if any((resolved / child).exists() for child in ("AppData", "Windows", "Program Files", ".ssh")):
            raise FilePolicyError("That location contains sensitive system data.")
        return resolved

    def resolve(self, root, relative="", must_exist=True):
        safe_relative(relative)
        roots = self.snapshot()
        if root not in roots: raise FilePolicyError("That location has not been approved.")
        base = self._approved_root(roots[root])
        candidate = base.joinpath(*relative.replace("\\", "/").split("/")) if relative else base
        check_path_chain(candidate)
        resolved = candidate.resolve(strict=must_exist)
        if not resolved.is_relative_to(base): raise FilePolicyError("Path is outside its approved location.")
        check_path_chain(resolved)
        return resolved

    def add_project(self, path, cancel_event=None):
        with self._lock:
            if cancel_event and cancel_event.is_set(): raise FilePolicyError("Approval cancelled.")
            resolved = self._approved_root(Path(path))
            roots = self.snapshot()
            key = "project_1"
            number = 1
            while key in roots:
                if roots[key] == resolved: return key
                number += 1; key = f"project_{number}"
            roots[key] = resolved
            if cancel_event and cancel_event.is_set(): raise FilePolicyError("Approval cancelled.")
            if self.settings_path:
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                data = {"project_roots": {name: str(value) for name, value in roots.items() if name not in KNOWN_ROOTS}}
                self.settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._roots = roots
            return key
