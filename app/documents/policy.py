"""Strict public document arguments; resolved paths never come from a model."""
import re
from typing import Literal

from pydantic import field_validator
from app.security.filesystem_policy import RootArgs, safe_component

DOCUMENT_TOOLS = frozenset({"summarize_pdf", "locate_pdf"})


def allowed_document_root(root):
    return root in {"desktop", "documents", "downloads"} or re.fullmatch(r"project_[1-9]\d*", root) is not None


class PdfArgs(RootArgs):
    query: str
    summary_style: Literal["concise", "detailed", "bullet_points"] = "concise"

    @field_validator("root")
    @classmethod
    def root_allowed(cls, value):
        if value != "all" and not allowed_document_root(value):
            raise ValueError("That document root is not approved.")
        return value

    @field_validator("query")
    @classmethod
    def query_allowed(cls, value):
        safe_component(value)
        if not value.strip() or ("." in value and not value.lower().endswith(".pdf")):
            raise ValueError("Use a PDF filename or a safe name fragment.")
        return value
