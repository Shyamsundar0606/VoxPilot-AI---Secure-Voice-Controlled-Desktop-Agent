import re
from app.models import ToolRequest


def document_request(command):
    match = re.fullmatch(r"(summarize(?: my)?|give me the main points from|locate|find) (.+?)(?: in (\w+))?", command.strip(), re.I | re.S)
    if not match:
        return None
    action, query, root = match.groups()
    if action.lower() in {"find", "locate"} and not query.lower().endswith(".pdf"):
        return None
    return ToolRequest(tool_name="locate_pdf" if action.lower() in {"find", "locate"} else "summarize_pdf",
                       arguments={"root": (root or "all").lower(), "query": query, "summary_style": "concise"})
