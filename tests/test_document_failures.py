"""Real spawned extraction -> service -> CommandWorker -> MainWindow failures."""
from dataclasses import replace
from threading import Event
from time import monotonic, sleep
from unittest.mock import Mock

import pytest
from pypdf import PdfReader

from app.agent.executor import CommandExecutor
from app.documents.extraction import extract
from app.documents.errors import DocumentError, DocumentFailureCode, SAFE_MESSAGES
from app.documents.limits import PdfLimits
from app.documents.process import run_isolated, _child
from app.documents.service import DocumentService
from app.models import Status
from tests.test_documents import write_pdf, TEXT
from tests.test_filesystem import fs
from tests.test_runtime import _window, _app


def stalled_extraction(*args, progress):
    progress("Extracting PDF", "Page 1 of 1")
    sleep(30)


@pytest.mark.parametrize("kind,code", [
    ("scanned", DocumentFailureCode.INSUFFICIENT_TEXT),
    ("malformed", DocumentFailureCode.MALFORMED),
    ("encrypted", DocumentFailureCode.ENCRYPTED),
    ("oversized", DocumentFailureCode.FILE_TOO_LARGE),
    ("timeout", DocumentFailureCode.EXTRACTION_TIMEOUT),
])
def test_failure_through_real_process_and_ui(fs, kind, code):
    expected = SAFE_MESSAGES[code]
    path = fs[1] / "report.pdf"
    limits = PdfLimits()
    if kind == "malformed": path.write_bytes(b"%PDF-1.7\nnot a valid document")
    else:
        write_pdf(path, ("123456789",) if kind == "scanned" else (TEXT,), encrypted=kind == "encrypted")
        if kind == "oversized":
            with path.open("ab") as stream: stream.write(b" " * 1024**2)
            limits = replace(limits, max_size_mb=1)
    if kind == "scanned":
        # Reproduce the observed small but nonzero extraction without printing it.
        contents = path.read_bytes()
        path.write_bytes(b"%PDF-1.7" + contents[8:])
        reader = PdfReader(path)
        assert reader.pdf_header == "%PDF-1.7"
        assert len(reader.pages) == 1 and not reader.is_encrypted
        assert len(reader.pages[0].extract_text()) == 9

    def runner(operation, arguments, limits, cancel, progress):
        if kind == "timeout" and operation is extract:
            # Only the parser body is replaced; real process/deadline handling remains.
            return run_isolated(stalled_extraction, arguments, limits, cancel, progress, timeout=.2)
        return run_isolated(operation, arguments, limits, cancel, progress)

    client = Mock()
    service = DocumentService(fs[0].roots, client, limits, runner=runner)
    window = _window(executor=CommandExecutor(documents=service))
    received = []
    try:
        window.input.setText("Summarize report.pdf in Documents")
        window.execute_command()
        window._active_worker.finished.connect(received.append)
        deadline = monotonic() + 15
        while window._active_thread is not None and monotonic() < deadline:
            _app().processEvents(); sleep(.002)
        assert window._active_thread is None
        assert len(received) == 1 and received[0].status == Status.FAILED
        assert received[0].document_failure_code == code
        assert window.status.text() == "Status: Failed"
        assert received[0].result_message == expected
        assert window.result_panel.toPlainText() == expected
        assert str(fs[1]) not in window.result_panel.toPlainText()
        client.summarize_text.assert_not_called()
        window.repository.add.assert_not_called()
    finally:
        window.stop()
        deadline = monotonic() + 3
        while window._active_thread is not None and monotonic() < deadline:
            _app().processEvents(); sleep(.002)
        window.close()


def raise_typed_failure(code, progress):
    raise DocumentError(DocumentFailureCode(code))


def raise_unexpected_failure(progress):
    raise RuntimeError("PRIVATE_EXCEPTION_MARKER C:\\Users\\private\\document.pdf")


@pytest.mark.parametrize("code", [DocumentFailureCode.INSUFFICIENT_TEXT, DocumentFailureCode.MALFORMED,
    DocumentFailureCode.ENCRYPTED, DocumentFailureCode.FILE_TOO_LARGE, DocumentFailureCode.EXTRACTION_TIMEOUT])
def test_typed_reason_survives_real_process(code):
    with pytest.raises(DocumentError) as failure:
        run_isolated(raise_typed_failure, (code.value,), PdfLimits(), Event(), lambda *_: None)
    assert failure.value.code == code and str(failure.value) == SAFE_MESSAGES[code]


def test_unexpected_exception_does_not_claim_invalid_pdf_or_leak_details():
    with pytest.raises(DocumentError) as failure:
        run_isolated(raise_unexpected_failure, (), PdfLimits(), Event(), lambda *_: None)
    assert failure.value.code == DocumentFailureCode.UNKNOWN
    assert "PRIVATE_EXCEPTION_MARKER" not in str(failure.value)
    assert "resource limit" not in str(failure.value) and "invalid file" not in str(failure.value)


@pytest.mark.parametrize("payload", ["PRIVATE_EXCEPTION_MARKER", {"code": "unrecognized"},
    {"code": "insufficient_text", "message": "PRIVATE_EXCEPTION_MARKER"}, {"message": "PRIVATE_EXCEPTION_MARKER"},
    {"code": ["insufficient_text"]}, None])
def test_error_payload_rejects_unrecognized_fields_and_text(payload):
    error = DocumentError.from_payload(payload)
    assert error.code == DocumentFailureCode.UNKNOWN
    assert str(error) == SAFE_MESSAGES[DocumentFailureCode.UNKNOWN]


def test_error_wire_payload_contains_only_allowlisted_code(monkeypatch):
    import logging
    import app.documents.process as module
    monkeypatch.setattr(module, "memory_limit", lambda _: None)
    sender = Mock()
    previous = logging.root.manager.disable
    try:
        _child(sender, raise_typed_failure, (DocumentFailureCode.INSUFFICIENT_TEXT.value,), 512)
    finally:
        logging.disable(previous)
    sender.send.assert_called_once_with(("error", {"code": "insufficient_text"}))
    sender.close.assert_called_once()


def test_ui_renders_catalog_message_instead_of_exception_details():
    from app.models import ExecutionResult
    window = _window()
    try:
        result = ExecutionResult(original_command="", normalized_command="", selected_tool="summarize_pdf",
            status=Status.FAILED, result_message="PRIVATE_EXCEPTION_MARKER C:\\private.pdf",
            document_failure_code=DocumentFailureCode.INSUFFICIENT_TEXT, store_history=False)
        window._complete(result)
        assert window.result_panel.toPlainText() == SAFE_MESSAGES[DocumentFailureCode.INSUFFICIENT_TEXT]
        window.repository.add.assert_not_called()
    finally: window.close()


@pytest.mark.parametrize("minimum,expected_code", [(10, DocumentFailureCode.INSUFFICIENT_TEXT), (9, None)])
def test_configured_minimum_is_used_in_real_extraction(fs, minimum, expected_code):
    from app.documents.extraction import locate
    from tests.test_documents import request
    write_pdf(fs[1] / "report.pdf", ("123456789",))
    limits = replace(PdfLimits(), min_characters=minimum)
    choice = locate(fs[0].roots.configuration(), request().arguments)[0]
    if expected_code:
        with pytest.raises(DocumentError) as failure:
            run_isolated(extract, (fs[0].roots.configuration(), choice, limits), limits, Event(), lambda *_: None)
        assert failure.value.code == expected_code
    else:
        result = run_isolated(extract, (fs[0].roots.configuration(), choice, limits), limits, Event(), lambda *_: None)
        assert len(result["pages"][0][1]) == 9


def test_minimum_configuration(monkeypatch, tmp_path):
    from app.config import Settings
    monkeypatch.setenv("VOXPILOT_PDF_MIN_CHARACTERS", "37")
    settings = Settings(database_path=tmp_path / "history.sqlite3", voice_settings_path=tmp_path / "voice.json",
                        recordings_path=tmp_path / "recordings", approved_roots_path=tmp_path / "roots.json")
    assert PdfLimits.from_settings(settings).min_characters == 37
    for minimum in (0, -1, True, 200001):
        with pytest.raises(ValueError): replace(PdfLimits(), min_characters=minimum)
