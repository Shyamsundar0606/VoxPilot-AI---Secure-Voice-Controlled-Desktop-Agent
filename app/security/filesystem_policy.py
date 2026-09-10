"""Logical-root filesystem policy. No model-supplied absolute paths."""
from pathlib import Path, PureWindowsPath
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator


FILESYSTEM_TOOLS = frozenset({"open_folder", "list_directory", "find_file", "create_folder", "file_info"})
KNOWN_ROOTS = ("desktop", "documents", "downloads", "pictures", "music", "videos")
DENIED_PARTS = frozenset({"windows", "system32", "program files", "program files (x86)", "programdata",
    "appdata", ".ssh", ".git", ".venv", "venv", "env", "credentials", "credential", "secrets",
    "user data", "profiles", "browser profiles", "mozilla", "microsoftedge", "google chrome", "credential manager"})


class FilePolicyError(ValueError):
    pass


def safe_component(name):
    if not isinstance(name, str) or not name or len(name) > 120:
        raise FilePolicyError("A name must contain 1–120 characters.")
    if (name in {".", ".."} or name.endswith((".", " ")) or name.startswith(".")
            or name.casefold() in DENIED_PARTS or any(c in '<>:"/\\|?*' for c in name)
            or any(unicodedata.category(c).startswith("C") or c in "\u2028\u2029" for c in name)):
        raise FilePolicyError("That name or location is not approved.")
    if re.fullmatch(r"(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?", name, re.I):
        raise FilePolicyError("Windows device names are not allowed.")
    return name


def safe_relative(value):
    if not isinstance(value, str) or len(value) > 400:
        raise FilePolicyError("Invalid relative path.")
    if value == "": return value
    windows = PureWindowsPath(value)
    if windows.drive or windows.root or value.startswith(("/", "\\")):
        raise FilePolicyError("Use an approved location name, not an absolute path.")
    for part in value.replace("\\", "/").split("/"): safe_component(part)
    return value.replace("\\", "/")


class RootArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    root: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")


class PathArgs(RootArgs):
    relative_path: str
    _relative = field_validator("relative_path")(safe_relative)


class ListArgs(PathArgs):
    kind: str = "all"

    @field_validator("kind")
    @classmethod
    def kind_allowed(cls, value):
        if value not in {"all", "files", "folders"}: raise ValueError("Invalid listing kind")
        return value


class FindArgs(RootArgs):
    query: str
    max_results: int = Field(default=20, ge=1, le=100)
    _query = field_validator("query")(safe_component)


class CreateArgs(RootArgs):
    relative_parent: str
    folder_name: str
    _parent = field_validator("relative_parent")(safe_relative)
    _name = field_validator("folder_name")(safe_component)


FILE_SCHEMAS = {"open_folder": PathArgs, "list_directory": ListArgs, "file_info": PathArgs,
                "find_file": FindArgs, "create_folder": CreateArgs}


def validate_file_arguments(tool, arguments):
    return FILE_SCHEMAS[tool].model_validate(arguments).model_dump()


def check_path_chain(path: Path):
    """Reject all links/reparse points, including ancestors of an approved root."""
    for part in reversed((path, *path.parents)):
        if part == Path(part.anchor): continue
        if part.name.casefold() in DENIED_PARTS or part.name.startswith("."):
            raise FilePolicyError("Sensitive locations are not approved.")
        if part.is_symlink() or part.is_junction():
            raise FilePolicyError("Linked locations are not approved.")
        if part.exists():
            if part.is_dir() and ((part / "pyvenv.cfg").exists() or (part / "conda-meta").is_dir()):
                raise FilePolicyError("Virtual environments are not approved.")
            attrs = getattr(part.stat(follow_symlinks=False), "st_file_attributes", 0)
            if attrs & (0x400 | 0x2 | 0x4):
                raise FilePolicyError("Hidden, system or redirected locations are not approved.")
