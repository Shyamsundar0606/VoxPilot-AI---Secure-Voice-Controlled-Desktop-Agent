"""Clear file commands map to logical roots, never absolute paths."""
import re
from app.models import ToolRequest


def file_request(command):
    text = command.strip(" ")
    patterns = [
        (r"open (?:my )?(desktop|documents|downloads|pictures|music|videos|project_\d+)(?: folder)?", "open_folder"),
        (r"(?:show|list) (files|folders|entries) in (\w+)", "list_directory"),
        (r"find (?:my |files? named )?(.+?) in (\w+)", "find_file"),
        (r"find files? named (.+)", "find_all"),
        (r"create (?:a )?folder called (.+?) in (\w+)", "create_folder"),
        (r"show information about (.+?)(?: in (\w+))?", "file_info"),
    ]
    for pattern, tool in patterns:
        match = re.fullmatch(pattern, text, re.I | re.S)
        if not match: continue
        if tool == "open_folder": args = {"root": match[1].lower(), "relative_path": ""}
        elif tool == "list_directory":
            args = {"root": match[2].lower(), "relative_path": "", "kind": {"entries": "all"}.get(match[1].lower(), match[1].lower())}
        elif tool == "find_file": args = {"root": match[2].lower(), "query": match[1], "max_results": 20}
        elif tool == "find_all":
            tool = "find_file"; args = {"root": "all", "query": match[1], "max_results": 20}
        elif tool == "create_folder": args = {"root": match[2].lower(), "relative_parent": "", "folder_name": match[1]}
        else: args = {"root": (match[2] or "documents").lower(), "relative_path": match[1]}
        return ToolRequest(tool_name=tool, arguments=args)
    return None
