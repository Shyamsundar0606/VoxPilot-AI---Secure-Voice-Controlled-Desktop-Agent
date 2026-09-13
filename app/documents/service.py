"""Document orchestration and expiring, one-use selections."""
from dataclasses import dataclass
import logging
import secrets
from threading import Event, RLock
from time import monotonic

from app.documents.extraction import locate, extract
from app.documents.limits import PdfLimits
from app.documents.policy import PdfArgs
from app.documents.process import run_isolated
from app.documents.errors import DocumentError, DocumentFailureCode
from app.documents.summarizer import summarize
from app.agent.ollama_client import OllamaError
from app.models import ExecutionResult, Status

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Selection:
    token: str
    choices: tuple
    style: str
    deadline: float


class DocumentService:
    def __init__(self, roots, client, limits=None, runner=run_isolated, clock=monotonic):
        self.roots, self.client = roots, client
        self.limits, self.runner, self.clock = limits or PdfLimits(), runner, clock
        self._selection = None
        self._lock = RLock()

    def cancel_selection(self):
        with self._lock: self._selection = None

    def execute(self, request=None, cancel_event=None, progress=lambda *_: None, selection=None):
        cancel = cancel_event or Event()
        started = self.clock()
        extracted = None
        try:
            if cancel.is_set(): raise DocumentError("Document task cancelled.")
            if selection:
                token, number = selection
                with self._lock:
                    pending, self._selection = self._selection, None
                if not pending or pending.token != token or self.clock() >= pending.deadline:
                    raise DocumentError("PDF selection expired or was cancelled. Locate it again.")
                if type(number) is not int or not 1 <= number <= len(pending.choices):
                    raise DocumentError("Invalid PDF selection.")
                choice, style = pending.choices[number - 1], pending.style
            else:
                self.cancel_selection()
                if request.tool_name not in {"summarize_pdf", "locate_pdf"}: raise DocumentError("Document tool is not approved.")
                args = PdfArgs.model_validate(request.arguments)
                progress("Locating PDF", "Searching approved locations")
                choices = self.runner(locate, (self.roots.configuration(), args.model_dump()), self.limits, cancel, progress)
                if cancel.is_set(): raise DocumentError("Document task cancelled.")
                if not choices: raise DocumentError("No matching PDF found in the approved locations.")
                if len(choices) > 1 or request.tool_name == "locate_pdf":
                    token = secrets.token_urlsafe(24)
                    with self._lock:
                        self._selection = Selection(token, tuple(choices), args.summary_style, self.clock() + self.limits.selection_timeout)
                    result = self._result(Status.AWAITING_SELECTION, "Select one PDF to summarize:\n" + "\n".join(f"{i + 1}. {c.label}" for i, c in enumerate(choices)))
                    result.document_selection = {"token": token, "labels": [c.label for c in choices], "timeout": self.limits.selection_timeout}
                    return result
                choice, style = choices[0], args.summary_style
            progress("Extracting PDF", "Validating selected PDF")
            extracted = self.runner(extract, (self.roots.configuration(), choice, self.limits), self.limits, cancel, progress)
            summary = summarize(extracted, self.client, style, self.limits, cancel, progress)
            if cancel.is_set(): raise DocumentError("Document task cancelled.")
            result = self._result(Status.COMPLETED, choice.relative.split("/")[-1] + "\n\n" + summary)
            overview = summary.split("Main points:")[0].strip()
            result.spoken_message = overview[:self.limits.spoken_characters]
            return result
        except DocumentError as exc:
            failure = DocumentError(DocumentFailureCode.CANCELLED) if cancel.is_set() else exc
            result = self._result(Status.CANCELLED if failure.code == DocumentFailureCode.CANCELLED else Status.FAILED, str(failure))
            result.document_failure_code = failure.code
            return result
        except OllamaError as exc:
            message = ("Local PDF summarization timed out. Please retry or use a smaller PDF."
                       if "timed out" in str(exc).lower() else "Local Ollama is unavailable or returned an invalid response. Start the local model and retry.")
            return self._result(Status.CANCELLED if cancel.is_set() else Status.FAILED,
                                "Document task cancelled." if cancel.is_set() else message)
        except Exception:
            return self._result(Status.CANCELLED if cancel.is_set() else Status.FAILED,
                "Document task cancelled." if cancel.is_set() else "PDF processing or local Ollama is unavailable. Please check the file and local model, then retry.")
        finally:
            if cancel.is_set(): self.cancel_selection()
            if extracted: extracted["pages"].clear()
            logger.info("Document task finished: elapsed=%.3fs cancelled=%s", self.clock() - started, cancel.is_set())

    @staticmethod
    def _result(status, message):
        return ExecutionResult(original_command="[Local PDF request]", normalized_command="", selected_tool="summarize_pdf",
                               status=status, result_message=message, store_history=False)
