"""Untrusted language in; independently policy-validated tool requests out."""
import logging
import re
from dataclasses import dataclass
from threading import Event
from time import perf_counter

from app.agent.ollama_client import OllamaError
from app.agent.schemas import parse_intent
from app.models import ToolRequest
from app.security.validators import validate_tool_request
from app.security.filesystem_policy import FILESYSTEM_TOOLS
from app.voice.wake_word import is_wake_phrase

logger = logging.getLogger(__name__)

BLOCKED = re.compile(
    r"\b(delete|remove|destroy|purge|erase|wipe|format|shutdown|shut\s+down|power\s+off|restart|reboot|"
    r"powershell|cmd|command\s+prompt|terminal|shell|registry|regedit|install|uninstall|"
    r"disable|defender|firewall|antivirus|security|sudo|execute|script|code|"
    r"ignore|override|bypass|system\s+prompt|instructions|pretend|role|"
    r"password|passwd|secret|token|api\s*key|private\s*key|credential|bearer)\b"
    r"|https?://|www\.|[a-z]:[\\/]|[/\\]|[;`{}]|\$\(|\.exe\b", re.I)


@dataclass(frozen=True)
class Plan:
    request: ToolRequest | None = None
    message: str = "The request is unsupported or ambiguous. Please use an exact approved command."


class IntentPlanner:
    def __init__(self, client, min_confidence=0.85):
        if not 0 <= min_confidence <= 1: raise ValueError("Invalid intent confidence threshold")
        self.client, self.min_confidence = client, min_confidence

    def plan(self, text, cancel_event=None):
        cancel = cancel_event or Event()
        started = perf_counter()
        intent, accepted = "none", False
        try:
            if cancel.is_set(): return Plan(message="Intent request cancelled.")
            if is_wake_phrase(text): return Plan(message="Wake phrase consumed.")
            if not text.strip() or len(text) > 500 or BLOCKED.search(text): return Plan()
            if re.search(r"\b(no|not|never|don['’]?t|except|without)\b", text, re.I): return Plan()
            # One action only; never let one approved sub-action launder a compound request.
            if re.search(r"\b(and|then|also|or)\b", text, re.I): return Plan()
            parsed = parse_intent(self.client.complete(text, cancel))
            intent = parsed.intent
            if cancel.is_set(): return Plan(message="Intent request cancelled.")
            from app.security.policy import CONFIRMATION_REQUIRED_TOOLS
            if parsed.confidence < self.min_confidence or (parsed.requires_confirmation and parsed.intent not in CONFIRMATION_REQUIRED_TOOLS): return Plan()
            request = parsed.to_request()
            validate_tool_request(request)
            if not self._grounded(text, request): return Plan()
            accepted = True
            return Plan(request=request, message="Intent validated.")
        except OllamaError as exc:
            return Plan(message=str(exc))
        except Exception:
            # Model content and validation details may contain sensitive strings.
            return Plan(message="The local model returned an invalid or unsafe intent. Please use an exact command.")
        finally:
            logger.info("Intent plan: intent=%s accepted=%s elapsed=%.3fs", intent, accepted, perf_counter() - started)

    @staticmethod
    def _grounded(text, request):
        """Require a recognizable target; model confidence alone cannot authorize it."""
        from app.projects.policy import PROJECT_TOOLS
        if request.tool_name in PROJECT_TOOLS:
            if not re.search(r"\bprojects?\b", text, re.I): return False
            cues = {"list_projects": "list|show|discover", "open_project": "open", "get_project_info": "info|information|details",
                    "start_project": "start|run", "stop_project": "stop", "list_running_projects": "running"}
            if not re.search(r"\b(?:" + cues[request.tool_name] + r")\b", text, re.I): return False
            return all(value == "all" or re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.I) for value in request.arguments.values())
        from app.documents.policy import DOCUMENT_TOOLS
        if request.tool_name in DOCUMENT_TOOLS:
            args = request.arguments
            return (re.search(r"\b(summarize|summary|main points|locate|find)\b", text, re.I) is not None
                    and args["query"].casefold() in text.casefold()
                    and (args["root"] == "all" or re.search(r"(?<!\w)" + re.escape(args["root"]) + r"(?!\w)", text, re.I) is not None))
        if request.tool_name in FILESYSTEM_TOOLS:
            args = request.arguments
            if re.search(r"(?<!\w)" + re.escape(args["root"]) + r"(?!\w)", text, re.I) is None: return False
            cues = {"open_folder": r"\b(open|show|folder)\b", "list_directory": r"\b(list|show|files|folders)\b",
                    "find_file": r"\b(find|locate|search)\b", "file_info": r"\b(info|information|size|details)\b",
                    "create_folder": r"\b(create|make|new)\b"}
            if re.search(cues[request.tool_name], text, re.I) is None: return False
            for key in ("relative_path", "relative_parent", "folder_name", "query"):
                value = args.get(key, "")
                if value and value.casefold() not in text.casefold(): return False
            return True
        if request.tool_name == "search_google":
            query = request.arguments["query"].strip()
            return (re.search(r"\bgoogle\b", text, re.I) is not None
                    and re.search(r"\b(search|find|look\s+up)\b", text, re.I) is not None
                    and re.search(r"(?<!\w)" + re.escape(query) + r"(?!\w)", text, re.I) is not None)
        words = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "
        targets = {
            "chrome": ("chrome", "browser"), "spotify": ("spotify",), "settings": ("settings",),
            "notepad": ("notepad",), "word": ("word",), "calculator": ("calculator",),
            "vscode": ("vs code", "visual studio code", "vscode"), "file_explorer": ("file explorer",),
            "google": ("google",), "chatgpt": ("chatgpt", "chat gpt"),
            "current_time": ("time", "clock"), "current_date": ("date", "day", "today"),
            "battery_status": ("battery", "charge", "power"),
            "storage_status": ("storage", "disk", "space", "drive"), "help": ("help", "commands", "do"),
        }
        target = request.arguments.get("application", request.arguments.get("url_name", request.tool_name))
        return any(f" {word} " in words for word in targets.get(target, ()))
