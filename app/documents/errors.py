"""Stable document failure codes with application-owned, path-free messages."""
from enum import StrEnum


class DocumentFailureCode(StrEnum):
    INSUFFICIENT_TEXT = "insufficient_text"
    MALFORMED = "malformed_pdf"
    ENCRYPTED = "encrypted_pdf"
    FILE_TOO_LARGE = "file_too_large"
    PAGE_LIMIT = "page_limit"
    EMPTY = "empty_pdf"
    INVALID_SIGNATURE = "invalid_signature"
    NOT_PDF = "not_pdf"
    FILE_CHANGED = "file_changed"
    CHANGED_DURING_EXTRACTION = "changed_during_extraction"
    INACCESSIBLE = "inaccessible_pdf"
    EXTRACTION_FAILED = "extraction_failed"
    EXTRACTION_TIMEOUT = "extraction_timeout"
    SUMMARY_TIMEOUT = "summary_timeout"
    CANCELLED = "cancelled"
    RESOURCE_LIMIT = "resource_limit"
    ISOLATION_UNAVAILABLE = "isolation_unavailable"
    PROCESS_UNAVAILABLE = "process_unavailable"
    WORKER_STOPPED = "worker_stopped"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    UNAPPROVED_ROOT = "unapproved_root"
    SEARCH_LIMIT = "search_limit"
    TOO_MANY_MATCHES = "too_many_matches"
    LOCATION_UNAVAILABLE = "location_unavailable"
    LOCATION_UNAPPROVED = "location_unapproved"
    SELECTION_EXPIRED = "selection_expired"
    INVALID_SELECTION = "invalid_selection"
    UNSUPPORTED_TOOL = "unsupported_tool"
    NOT_FOUND = "pdf_not_found"
    INVALID_SUMMARY = "invalid_summary"
    STRUCTURED_SUMMARY = "structured_summary"
    INVALID_CHUNK_LIMIT = "invalid_chunk_limit"
    NO_TEXT = "no_text"
    UNKNOWN = "document_failed"


SAFE_MESSAGES = {
    DocumentFailureCode.INSUFFICIENT_TEXT: "This PDF appears to be scanned or image-based. OCR is not available yet.",
    DocumentFailureCode.MALFORMED: "Malformed PDF or text extraction failure.",
    DocumentFailureCode.ENCRYPTED: "Encrypted or password-protected PDFs are not supported.",
    DocumentFailureCode.FILE_TOO_LARGE: "PDF exceeds the configured file-size limit.",
    DocumentFailureCode.PAGE_LIMIT: "PDF exceeds the configured page-count limit.",
    DocumentFailureCode.EMPTY: "The PDF has no pages.",
    DocumentFailureCode.INVALID_SIGNATURE: "Invalid PDF signature.",
    DocumentFailureCode.NOT_PDF: "Select a regular PDF file.",
    DocumentFailureCode.FILE_CHANGED: "The PDF changed after selection. Locate it again.",
    DocumentFailureCode.CHANGED_DURING_EXTRACTION: "The PDF changed during extraction. Please retry.",
    DocumentFailureCode.INACCESSIBLE: "The PDF is unavailable or inaccessible.",
    DocumentFailureCode.EXTRACTION_FAILED: "PDF text extraction failed.",
    DocumentFailureCode.EXTRACTION_TIMEOUT: "PDF extraction or location timed out. Please narrow the request.",
    DocumentFailureCode.SUMMARY_TIMEOUT: "PDF summarization timed out.",
    DocumentFailureCode.CANCELLED: "Document task cancelled.",
    DocumentFailureCode.RESOURCE_LIMIT: "PDF processing exceeded the configured memory resource limit.",
    DocumentFailureCode.ISOLATION_UNAVAILABLE: "PDF memory isolation is unavailable.",
    DocumentFailureCode.PROCESS_UNAVAILABLE: "PDF processing is unavailable.",
    DocumentFailureCode.WORKER_STOPPED: "PDF worker stopped unexpectedly. Please retry.",
    DocumentFailureCode.DEPENDENCY_UNAVAILABLE: "The local PDF extraction dependency is unavailable. Install the project requirements and retry.",
    DocumentFailureCode.UNAPPROVED_ROOT: "That document root is not approved.",
    DocumentFailureCode.SEARCH_LIMIT: "PDF search limit reached. Use a more specific filename and root.",
    DocumentFailureCode.TOO_MANY_MATCHES: "Too many matching PDFs. Use a more specific filename and root.",
    DocumentFailureCode.LOCATION_UNAVAILABLE: "The PDF location is unavailable or inaccessible.",
    DocumentFailureCode.LOCATION_UNAPPROVED: "The PDF location is not approved or accessible.",
    DocumentFailureCode.SELECTION_EXPIRED: "PDF selection expired or was cancelled. Locate it again.",
    DocumentFailureCode.INVALID_SELECTION: "Invalid PDF selection.",
    DocumentFailureCode.UNSUPPORTED_TOOL: "Document tool is not approved.",
    DocumentFailureCode.NOT_FOUND: "No matching PDF found in the approved locations.",
    DocumentFailureCode.INVALID_SUMMARY: "The summarizer returned invalid text.",
    DocumentFailureCode.STRUCTURED_SUMMARY: "Structured or executable summarizer output was rejected.",
    DocumentFailureCode.INVALID_CHUNK_LIMIT: "PDF chunk limit is too small.",
    DocumentFailureCode.NO_TEXT: "No extractable document text.",
    DocumentFailureCode.UNKNOWN: "PDF processing failed safely. Please retry.",
}


class DocumentError(ValueError):
    def __init__(self, reason=DocumentFailureCode.UNKNOWN):
        if isinstance(reason, DocumentFailureCode):
            self.code = reason
        else:
            # Compatibility for existing internal callers. Unknown exception text
            # is never displayed or sent across the process boundary.
            self.code = next((code for code, message in SAFE_MESSAGES.items() if reason == message), DocumentFailureCode.UNKNOWN)
        super().__init__(SAFE_MESSAGES[self.code])

    def to_payload(self):
        return {"code": self.code.value}

    @classmethod
    def from_payload(cls, payload):
        if type(payload) is dict and set(payload) == {"code"} and type(payload["code"]) is str:
            try:
                return cls(DocumentFailureCode(payload["code"]))
            except ValueError:
                pass
        return cls(DocumentFailureCode.UNKNOWN)
