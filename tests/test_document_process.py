"""Exercise real disposable parser processes, never Ollama or user documents."""
from dataclasses import replace
from threading import Event, Timer
from time import sleep, monotonic
import pytest

from app.documents.extraction import extract, locate
from app.documents.limits import PdfLimits
from app.documents.process import run_isolated, DocumentError
from tests.test_filesystem import fs
from tests.test_documents import write_pdf, request, TEXT


def slow_operation(progress):
    sleep(20)


def memory_operation(progress):
    allocation = bytearray(1024**3)
    return len(allocation)


def test_real_isolated_pdf_extract(fs):
    write_pdf(fs[1] / "report.pdf", (TEXT, TEXT))
    limits = PdfLimits(); cancel = Event(); events = []
    choices = run_isolated(locate, (fs[0].roots.configuration(), request().arguments), limits, cancel, lambda *_: None)
    extracted = run_isolated(extract, (fs[0].roots.configuration(), choices[0], limits), limits, cancel, lambda *args: events.append(args))
    assert len(extracted["pages"]) == 2 and len(events) == 2
    assert extracted["pages"][0][1] == TEXT


def test_extraction_wall_timeout_kills_worker():
    started = monotonic()
    with pytest.raises(DocumentError, match="timed out"):
        run_isolated(slow_operation, (), replace(PdfLimits(), extraction_timeout=.2), Event(), lambda *_: None)
    assert monotonic() - started < 5


def test_extraction_cancel_kills_worker():
    cancel = Event(); timer = Timer(.2, cancel.set); timer.start()
    try:
        started = monotonic()
        with pytest.raises(DocumentError, match="cancelled"):
            run_isolated(slow_operation, (), PdfLimits(), cancel, lambda *_: None)
        assert monotonic() - started < 5
    finally: timer.join()


def test_memory_limit_fails_safely():
    with pytest.raises(DocumentError, match="resource limit"):
        run_isolated(memory_operation, (), replace(PdfLimits(), memory_mb=128), Event(), lambda *_: None)
