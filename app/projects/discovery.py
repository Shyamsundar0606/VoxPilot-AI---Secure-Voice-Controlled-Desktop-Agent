"""Metadata-only traversal, bounded before scheduling each directory."""
import os
import re
from dataclasses import dataclass
from time import monotonic
from app.security.filesystem_policy import safe_component

MANIFESTS = {"pyproject.toml": "Python", "requirements.txt": "Python", "package.json": "Node",
             "docker-compose.yml": "Compose", "docker-compose.yaml": "Compose", "compose.yml": "Compose",
             "compose.yaml": "Compose", "Cargo.toml": "Rust", "go.mod": "Go"}
SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}


@dataclass(frozen=True)
class DiscoveryLimits:
    depth: int = 3
    directories: int = 1000
    results: int = 100
    timeout: float = 15

    def __post_init__(self):
        if not (0 <= self.depth <= 10 and 1 <= self.directories <= 10000 and 1 <= self.results <= 1000 and 0 < self.timeout <= 60):
            raise ValueError("Invalid discovery limits")


def discover(roots, limits, cancel, root="all", clock=monotonic):
    deadline = clock() + limits.timeout
    pending = [(key, "", 0) for key in sorted(roots.snapshot())
               if re.fullmatch(r"project_[1-9][0-9]*", key) and root in ("all", key)]
    found, inspected = [], 0
    while pending and inspected < limits.directories and len(found) < limits.results:
        if cancel.is_set(): raise ValueError("Project discovery cancelled.")
        if clock() >= deadline: raise ValueError("Project discovery timed out. Reduce the discovery limits.")
        key, relative, depth = pending.pop(0)
        inspected += 1
        try:
            directory = roots.resolve(key, relative)
            types, children = set(), []
            # Bound even extremely wide directories; never materialize an unbounded scandir.
            with os.scandir(directory) as entries:
                for count, entry in enumerate(entries):
                    if cancel.is_set(): raise InterruptedError()
                    if clock() >= deadline: raise TimeoutError()
                    if count >= limits.directories: break
                    if entry.name.startswith(".") or entry.name.casefold() in SKIP: continue
                    try:
                        safe_component(entry.name)
                        child = roots.resolve(key, "/".join(filter(None, (relative, entry.name))))
                        if child.is_file() and entry.name in MANIFESTS: types.add(MANIFESTS[entry.name])
                        elif child.is_dir() and depth < limits.depth: children.append(entry.name)
                    except ValueError: continue
            if types:
                found.append({"name": directory.name, "root": key, "relative": relative,
                              "type": "/".join(sorted(types)), "actions": ["open", "info"]})
            room = limits.directories - inspected - len(pending)
            pending.extend((key, "/".join(filter(None, (relative, name))), depth + 1) for name in sorted(children, key=lambda x: (x.casefold(), x))[:max(0, room)])
        except (InterruptedError, TimeoutError):
            raise ValueError("Project discovery cancelled or timed out.") from None
        except (ValueError, OSError): continue
    return sorted(found, key=lambda p: (p["name"].casefold(), p["root"], p["relative"]))
