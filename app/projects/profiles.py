"""Profiles are local configuration, never model output or command text."""
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.security.filesystem_policy import safe_relative

SENSITIVE = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH", re.I)
SAFE_ENV = frozenset({"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "PYTHONUTF8"})


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    root: str = Field(pattern=r"^project_[1-9][0-9]*$")
    directory: str
    runner: Literal["python_module", "python_script", "npm_script", "docker_compose"]
    executable: str
    entry_point: str
    arguments: list[str] = Field(default_factory=list, max_length=32)
    working_directory: str = ""
    environment_allowlist: list[str] = Field(default_factory=list, max_length=16)
    allow_duplicate: bool = False
    npm_cli: str | None = None

    @field_validator("directory", "working_directory")
    @classmethod
    def relative(cls, value):
        safe_relative(value)
        if re.search(r"[;&`$(){}]", value): raise ValueError("Shell metacharacters are not permitted in launch paths")
        return value

    @field_validator("display_name")
    @classmethod
    def name(cls, value):
        from app.projects.policy import ProjectArgs
        return ProjectArgs(project=value).project

    @field_validator("arguments")
    @classmethod
    def fixed_args(cls, values):
        for value in values:
            if not value or len(value) > 200 or any(unicodedata.category(c).startswith("C") for c in value) or re.search(r"[;&|`$<>\r\n\x00{}()]|\.\.|[\\/]|^[a-zA-Z]:", value):
                raise ValueError("Arguments must be fixed simple values, never paths or shell syntax")
        return values

    @field_validator("environment_allowlist")
    @classmethod
    def safe_environment(cls, values):
        if any(SENSITIVE.search(v) or v.upper() not in SAFE_ENV for v in values):
            raise ValueError("Only documented safe environment names may be inherited")
        return values


def fingerprint(path):
    path = Path(path)
    stat = path.stat()
    return [str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def read_metadata(path):
    with Path(path).open("rb") as stream: data = stream.read(65537)
    if len(data) > 65536: raise ValueError("Project manifest exceeds the metadata limit")
    return data


def native_path(path):
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)(): raise ValueError("Executable links are prohibited")
        if part.exists() and getattr(part.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400:
            raise ValueError("Executable reparse points are prohibited")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class Executables:
    def resolve(self, value, runner, project):
        path = Path(value)
        if not path.is_absolute() or str(path).startswith(("\\\\", "//")): raise ValueError("Configure an absolute executable")
        from app.filesystem.platform import WindowsFolders
        if not WindowsFolders().fixed_drive(path): raise ValueError("Executable must be on a local fixed drive")
        # A local interpreter may live in .venv, but no symlink/reparse component may be followed.
        native_path(path)
        resolved = path.resolve(strict=True)
        names = {"python_module": {"python.exe"}, "python_script": {"python.exe"},
                 "npm_script": {"node.exe"}, "docker_compose": {"docker.exe"}}
        if resolved.name.casefold() not in names[runner] or not resolved.is_file(): raise ValueError("Unapproved executable type")
        # Require a native Windows executable; never .cmd/.bat scripts or shell wrappers.
        with resolved.open("rb") as stream:
            if stream.read(2) != b"MZ": raise ValueError("A native Windows executable is required")
        return resolved


def compose_metadata(data):
    # JSON is a YAML subset. Restrict Compose to JSON syntax to avoid YAML aliases,
    # custom tags, implicit coercion and any additional parser dependency.
    spec = json.loads(data)
    if not isinstance(spec, dict) or set(spec) != {"services"}: raise ValueError("Compose requires only services")
    services = spec["services"]
    if not isinstance(services, dict) or not 1 <= len(services) <= 16: raise ValueError("Invalid Compose services")
    for name, service in services.items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", name): raise ValueError("Invalid service name")
        if not isinstance(service, dict) or set(service) - {"image", "init", "read_only"}: raise ValueError("Unsafe Compose option")
        # Digest pinning prevents a mutable image tag changing after confirmation.
        if not isinstance(service.get("image"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9./_-]*@sha256:[a-f0-9]{64}", service["image"]):
            raise ValueError("Compose images must be locally available and digest-pinned")
        if any(type(v) is not bool for k, v in service.items() if k != "image"): raise ValueError("Invalid Compose flag")
    return spec


class Profiles:
    def __init__(self, roots, path=None, platform=None):
        self.roots, self.path, self.platform = roots, Path(path) if path else None, platform or Executables()

    def load(self):
        if self.path is None or not self.path.exists(): return []
        data = json.loads(read_metadata(self.path))
        if not isinstance(data, list) or len(data) > 100: raise ValueError("Invalid profile configuration")
        profiles = [Profile.model_validate(p) for p in data]
        if len({p.project_id for p in profiles}) != len(profiles): raise ValueError("Duplicate profile identifiers")
        return profiles

    def save(self, raw, cancel):
        profile = Profile.model_validate(raw)
        self.plan(profile)
        profiles = [p for p in self.load() if p.project_id != profile.project_id] + [profile]
        if self.path is None or cancel.is_set(): raise ValueError("Profile saving cancelled or unavailable")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps([p.model_dump() for p in profiles], indent=2, ensure_ascii=False), encoding="utf-8")
        if cancel.is_set():
            temporary.unlink(missing_ok=True)
            raise ValueError("Profile saving cancelled")
        temporary.replace(self.path)
        return profile

    def plan(self, profile, instance=None):
        # Reparse because frozen models still contain mutable lists.
        profile = Profile.model_validate(profile.model_dump())
        project = self.roots.resolve(profile.root, profile.directory)
        cwd = self.roots.resolve(profile.root, "/".join(filter(None, (profile.directory, profile.working_directory))))
        if not cwd.is_dir() or not cwd.is_relative_to(project): raise ValueError("Invalid working directory")
        exe = self.platform.resolve(profile.executable, profile.runner, project)
        identities, contents = [fingerprint(project), fingerprint(cwd), fingerprint(exe)], {}
        def contained(relative):
            safe_relative(relative)
            if re.search(r"[;&`$(){}]", relative): raise ValueError("Invalid launch entry point")
            value = self.roots.resolve(profile.root, "/".join(filter(None, (profile.directory, relative))))
            if not value.is_file() or not value.is_relative_to(project): raise ValueError("Entry point must be inside the project")
            identities.append(fingerprint(value))
            return value
        args = list(profile.arguments)
        compose, instance = None, instance or uuid4().hex
        if profile.runner == "python_module":
            if cwd != project: raise ValueError("Python module working directory must be its approved project")
            if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", profile.entry_point, re.ASCII): raise ValueError("Invalid Python module")
            # Resolve an actual project module, never pip or another installed module.
            module = profile.entry_point.replace(".", "/")
            try: entry = contained(module + ".py")
            except (ValueError, OSError): entry = contained(module + "/__main__.py")
            argv = [str(exe), "-m", profile.entry_point, *args]
        elif profile.runner == "python_script":
            entry = contained(profile.entry_point)
            if entry.suffix.casefold() != ".py": raise ValueError("Python scripts must end in .py")
            argv = [str(exe), str(entry), *args]
        elif profile.runner == "npm_script":
            if args or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9:_-]{0,63}", profile.entry_point): raise ValueError("Invalid npm script")
            entry = contained("package.json")
            manifest = read_metadata(entry); contents[str(entry)] = hashlib.sha256(manifest).hexdigest()
            scripts = json.loads(manifest).get("scripts", {})
            if not isinstance(scripts.get(profile.entry_point), str) or not scripts[profile.entry_point].strip(): raise ValueError("The npm script is missing")
            # npm.cmd would require cmd.exe. Invoke npm's fixed CLI using validated node.exe.
            cli = Path(profile.npm_cli or "")
            if not cli.is_absolute() or cli.name != "npm-cli.js": raise ValueError("Configure npm-cli.js explicitly")
            native_path(cli); cli = cli.resolve(strict=True)
            if not cli.is_relative_to(exe.parent): raise ValueError("npm CLI must belong to the selected Node installation")
            identities.append(fingerprint(cli))
            argv = [str(exe), str(cli), "--ignore-scripts", "run-script", profile.entry_point]
        else:
            if args: raise ValueError("Compose options cannot be supplied")
            entry = contained(profile.entry_point)
            if entry.name not in {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}: raise ValueError("Invalid Compose filename")
            manifest = read_metadata(entry); compose_metadata(manifest)
            compose = manifest.decode("utf-8")
            contents[str(entry)] = hashlib.sha256(manifest).hexdigest()
            argv = [str(exe), "--host", "npipe:////./pipe/docker_engine", "compose", "--env-file", "NUL", "--project-directory", str(project),
                    "--project-name", "voxpilot-" + instance, "-f", "-", "up", "--no-build", "--pull", "never", "--abort-on-container-exit"]
        if profile.runner in {"python_module", "python_script"}:
            contents[str(entry)] = hashlib.sha256(read_metadata(entry)).hexdigest()
        environment = {k: v for k, v in os.environ.items() if k.upper() in {n.upper() for n in profile.environment_allowlist}
                       and k.upper() in SAFE_ENV and not SENSITIVE.search(k)}
        return {"profile": profile.model_dump(), "name": profile.display_name, "directory": str(project),
                "runner": profile.runner, "argv": argv, "cwd": str(cwd), "environment": environment,
                "identities": identities, "contents": contents, "instance": instance, "compose": compose}
