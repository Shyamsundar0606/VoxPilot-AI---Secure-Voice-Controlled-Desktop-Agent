import json
import os
import re
import tempfile
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
        self._retired = set()

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
                        if saved.get("version", 2) != 2: raise ValueError()
                        values = saved.get("roots") if saved.get("version") == 2 else {**self._roots, **saved.get("project_roots", {})}
                        loaded = {}
                        for key, value in values.items():
                            RootArgs(root=key)
                            if key not in KNOWN_ROOTS and not re.fullmatch(r"(?:document|project)_[1-9]\d*", key): raise ValueError()
                            if not isinstance(value, (str, Path)): raise ValueError()
                            loaded[key] = Path(value)
                        retired = saved.get("retired", [])
                        if not isinstance(retired, list): raise ValueError()
                        for key in retired: RootArgs(root=key)
                        self._retired = set(retired)
                        self._roots = loaded
                    except (OSError, ValueError, TypeError, AttributeError):
                        self._roots = None
                        raise FilePolicyError("Approved locations settings are invalid or unreadable; access is blocked.") from None
            return dict(self._roots)

    def _approved_root(self, path):
        path = Path(path)
        if not path.is_absolute() or str(path).startswith(("\\\\", "//")) or path == Path(path.anchor):
            raise FilePolicyError("Drive roots and network locations are not approved.")
        if not self.platform.fixed_drive(path):
            raise FilePolicyError("Only local fixed drives are approved.")
        for part in path.parts[1:]: safe_component(part)
        check_path_chain(path)
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            raise FilePolicyError("Approved folder is missing or unavailable.") from None
        check_path_chain(resolved)
        if not resolved.is_dir(): raise FilePolicyError("Approved location is not a folder.")
        repository = Path(__file__).resolve().parents[2]
        if resolved == Path.home().resolve() or repository.is_relative_to(resolved):
            raise FilePolicyError("The user profile, repository and their ancestors cannot be approved.")
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

    def _save(self, roots, retired):
        if not self.settings_path: return
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.settings_path.parent,
                                             prefix="approved-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"version": 2, "roots": {k: str(v) for k, v in roots.items()},
                           "retired": sorted(retired), "project_roots": {
                               k: str(v) for k, v in roots.items() if k.startswith("project_")}}, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.settings_path)
        finally:
            if temporary and temporary.exists(): temporary.unlink()

    def add(self, path, kind="document", cancel_event=None):
        if kind not in {"document", "project"}: raise FilePolicyError("Invalid approval type.")
        with self._lock:
            if cancel_event and cancel_event.is_set(): raise FilePolicyError("Approval cancelled.")
            resolved = self._approved_root(Path(path))
            roots = self.snapshot()
            for key, value in roots.items():
                same_kind = key.startswith(kind + "_") or (kind == "document" and key in {"desktop", "documents", "downloads"})
                if same_kind and value == resolved: return key
            key = f"{kind}_1"
            number = 1
            while key in roots or key in self._retired:
                number += 1; key = f"{kind}_{number}"
            roots[key] = resolved
            if cancel_event and cancel_event.is_set(): raise FilePolicyError("Approval cancelled.")
            self._save(roots, self._retired)
            self._roots = roots
            return key

    def add_project(self, path, cancel_event=None):
        return self.add(path, "project", cancel_event)

    def remove(self, key, *, confirmed=False, cancel_event=None):
        if not confirmed: raise FilePolicyError("Removing approval requires confirmation.")
        with self._lock:
            roots = self.snapshot()
            if key not in roots: raise FilePolicyError("That location has not been approved.")
            if cancel_event and cancel_event.is_set(): raise FilePolicyError("Removal cancelled.")
            del roots[key]
            retired = self._retired | {key}
            self._save(roots, retired)
            self._roots, self._retired = roots, retired

    def locations(self):
        rows = []
        for key, path in self.snapshot().items():
            try:
                self.resolve(key)
                status = "Available"
            except (OSError, ValueError):
                status = "Missing, unavailable or blocked by policy"
            rows.append({"id": key, "name": path.name, "path": str(path), "status": status,
                         "type": "Projects" if key.startswith("project_") else "Documents"})
        return rows
