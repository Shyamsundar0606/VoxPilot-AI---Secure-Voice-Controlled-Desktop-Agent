"""Bounded metadata-only operations with one confirmation-gated write."""
from collections import deque
from multiprocessing import get_context
from pathlib import Path
from threading import Event
from time import monotonic
import logging

from app.models import ToolRequest, ToolResult
from app.filesystem.roots import ApprovedRoots
from app.security.filesystem_policy import FilePolicyError, validate_file_arguments, safe_component

logger = logging.getLogger(__name__)


def _child_operation(sender, configuration, request, limits, expected):
    try:
        roots, settings_path = configuration
        service = FilesystemService(ApprovedRoots(roots=roots, settings_path=settings_path), isolated=False, **limits)
        result = service._perform(ToolRequest.model_validate(request), Event(), expected)
        sender.send(result.model_dump())
    except Exception:
        sender.send(ToolResult(success=False, message="The filesystem operation failed safely.").model_dump())
    finally:
        sender.close()


class FilesystemService:
    def __init__(self, roots, timeout=5.0, max_depth=4, max_results=100, isolated=True, clock=monotonic):
        if not 0 < timeout <= 30 or not 0 <= max_depth <= 10 or not 1 <= max_results <= 100:
            raise ValueError("Invalid filesystem limits")
        self.roots, self.timeout, self.max_depth, self.max_results = roots, timeout, max_depth, max_results
        self.isolated, self.clock = isolated, clock

    def execute(self, request, cancel_event=None, expected=None):
        cancel = cancel_event or Event()
        if not self.isolated: return self._perform(request, cancel, expected)
        started = monotonic()
        context = get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_child_operation, args=(sender, self.roots.configuration(), request.model_dump(),
            dict(timeout=self.timeout, max_depth=self.max_depth, max_results=self.max_results), expected), daemon=True)
        try:
            if cancel.is_set(): return ToolResult(success=False, message="Filesystem operation cancelled.")
            process.start(); sender.close()
            while True:
                if cancel.is_set(): return ToolResult(success=False, message="Filesystem operation cancelled.")
                if monotonic() - started >= self.timeout:
                    return ToolResult(success=False, message="Filesystem operation timed out. Please narrow the request.")
                if receiver.poll(0.02): return ToolResult.model_validate(receiver.recv())
                if not process.is_alive(): return ToolResult(success=False, message="Filesystem worker stopped safely.")
        except (OSError, EOFError, ValueError):
            return ToolResult(success=False, message="Filesystem operation is unavailable.")
        finally:
            if process.pid is not None:
                if process.is_alive(): process.terminate()
                process.join(); process.close()
            receiver.close(); sender.close()

    @staticmethod
    def identity(path):
        info = path.stat(follow_symlinks=False)
        return [str(path), info.st_dev, info.st_ino]

    def _perform(self, request, cancel, expected=None):
        started = self.clock()
        def check():
            if cancel.is_set(): raise FilePolicyError("Filesystem operation cancelled.")
            if self.clock() - started >= self.timeout: raise FilePolicyError("Filesystem operation timed out.")
        try:
            args = validate_file_arguments(request.tool_name, request.arguments)
            check()
            root = args["root"]
            resolve = lambda relative="", exists=True: self.roots.resolve(root, relative, exists)
            if request.tool_name == "create_folder":
                parent = resolve(args["relative_parent"])
                if not parent.is_dir(): raise FilePolicyError("The parent must be a folder.")
                relative = "/".join(filter(None, (args["relative_parent"], args["folder_name"])))
                destination = resolve(relative, False)
                if destination.exists(): raise FilePolicyError("The destination already exists.")
                identity = self.identity(parent)
                if expected is None:
                    return ToolResult(success=True, message="Confirm the proposed folder creation.", data={
                        "proposal": True, "parent": str(parent), "folder_name": args["folder_name"], "identity": identity})
                if identity != expected: raise FilePolicyError("The parent location changed. Request confirmation again.")
                check()
                if self.identity(resolve(args["relative_parent"])) != expected:
                    raise FilePolicyError("The parent location changed.")
                destination = resolve(relative, False)  # Final policy check immediately before the sole write.
                check(); destination.mkdir(exist_ok=False)
                return ToolResult(success=True, message=f"Created folder {args['folder_name']} in {root}.")
            if request.tool_name == "find_file":
                queue = deque([(key, "", 0) for key in self.roots.snapshot()] if root == "all" else [(root, "", 0)])
                matches, limited = [], False
                limit = min(args["max_results"], self.max_results)
                while queue:
                    check(); root, relative, depth = queue.popleft()
                    try: directory = resolve(relative)
                    except (ValueError, OSError):
                        if args["root"] == "all": continue
                        raise
                    for child in directory.iterdir():
                        check()
                        rel = "/".join(filter(None, (relative, child.name)))
                        try:
                            safe_component(child.name); checked = resolve(rel)
                        except (ValueError, OSError): continue
                        if checked.is_dir():
                            if depth < self.max_depth: queue.append((root, rel, depth + 1))
                            else: limited = True
                        elif checked.is_file() and args["query"].casefold() in child.name.casefold():
                            matches.append(root + "/" + rel if args["root"] == "all" else rel)
                            if len(matches) >= limit:
                                limited = True; queue.clear(); break
                return self._items(matches, limited)
            relative = args["relative_path"]
            path = resolve(relative)
            if request.tool_name == "open_folder":
                if not path.is_dir(): raise FilePolicyError("Only folders can be opened.")
                check(); path = resolve(relative)
                if not path.is_dir(): raise FilePolicyError("The folder changed.")
                self.roots.platform.open_folder(path)
                return ToolResult(success=True, message=f"Opened {root}" + (f" / {relative}." if relative else "."))
            if request.tool_name == "file_info":
                check(); path = resolve(relative); info = path.stat(follow_symlinks=False)
                return ToolResult(success=True, message=f"{path.name}: {'folder' if path.is_dir() else 'file'}, {info.st_size} bytes.",
                    data={"name": path.name, "size_bytes": info.st_size, "modified_timestamp": info.st_mtime, "is_folder": path.is_dir()})
            if not path.is_dir(): raise FilePolicyError("The location is not a folder.")
            entries, limited = [], False
            for child in resolve(relative).iterdir():
                check()
                rel = "/".join(filter(None, (relative, child.name)))
                try:
                    safe_component(child.name); checked = resolve(rel)
                except (ValueError, OSError): continue
                folder = checked.is_dir()
                if args["kind"] == "folders" and not folder: continue
                if args["kind"] == "files" and folder: continue
                if len(entries) >= self.max_results: limited = True; break
                entries.append(child.name + ("/" if folder else ""))
            return self._items(entries, limited)
        except FilePolicyError as exc:
            return ToolResult(success=False, message=str(exc))
        except (OSError, ValueError):
            return ToolResult(success=False, message="The location is unavailable, inaccessible or invalid.")
        finally:
            logger.info("Filesystem operation: tool=%s elapsed=%.3fs", request.tool_name, self.clock() - started)

    @staticmethod
    def _items(entries, limited):
        message = "\n".join(entries) or "No matching visible entries found."
        if limited: message += "\nResults truncated by the configured result or depth limit."
        return ToolResult(success=True, message=message, data={"entries": entries, "truncated": limited})
