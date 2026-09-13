# Milestone 6 verification — 2026-09-10

Implemented secure local extraction and summarization of text-based PDFs. No commit or push was created.

## Scanned-PDF error-reporting follow-up

Current verification after the error-reporting fix:

- Focused document suite: **128 passed in 16.41 seconds** using `tests/test_document_failures.py`, `tests/test_documents.py`, `tests/test_document_process.py`, `tests/test_document_ui.py`, and `tests/test_document_ollama.py` with `-q --tb=short`.
- Complete suite: **511 passed in 23.00 seconds**, no failures or skips, using `python -m pytest -q --tb=short`.
- `git diff --check`: passed. Nothing was staged or committed. `.env`, `.venv` and `venv` were not modified. The same temporary pypdf dependency directory was used.

Investigation: the original process protocol sent free-form error messages and the unexpected-exception fallback combined invalid-file and resource-limit explanations. It provided no typed reason to the service or UI. The original synthetic nine-character test reached the UI correctly, so that sample alone did not reproduce the reported generic fallback. The fix addresses the ambiguous protocol and protects the complete real signal path rather than inferring a scanned PDF from a generic exception.

`app/documents/errors.py` now owns stable `DocumentFailureCode` values and a safe message catalog. Extraction emits `INSUFFICIENT_TEXT` when normalized meaningful text is below `VOXPILOT_PDF_MIN_CHARACTERS` (default 20). Malformed, encrypted, oversized, page-limit, signature, access, memory and timeout failures remain distinct. The child sends only an allowlisted code; the parent validates the payload and reconstructs the safe error. The service adds the typed code to `ExecutionResult`; the existing CommandWorker/Qt relay preserves it. MainWindow displays only the locally defined message for that code, never raw child or exception details. Unknown exceptions no longer claim an invalid file or resource-limit cause without evidence.

End-to-end tests create synthetic PDFs and use real spawned processes, the service, CommandWorker, Qt signals and MainWindow. They verify scanned, malformed, encrypted, oversized and timed-out outcomes. The scanned fixture has a `%PDF-1.7` header, one unencrypted page and exactly nine extracted characters. Additional tests cover the configurable threshold (below and exactly at the minimum), typed-code serialization, unexpected exceptions, unknown/extra payload fields and UI message sanitization. No real documents, microphone or live model were used.

Files changed for this follow-up: new `app/documents/errors.py` and `tests/test_document_failures.py`; updated `app/documents/extraction.py`, `app/documents/process.py`, `app/documents/service.py`, `app/documents/limits.py`, `app/models.py`, `app/config.py`, `app/ui/main_window.py`, `tests/test_documents.py`, `.env.example`, `README.md` and this report. Other working-tree changes listed below belong to the existing uncommitted Milestone 6 implementation and were preserved.

## Initial Milestone 6 verification results

Python 3.12 on Windows. Existing `.venv/Scripts/python.exe` was used without installing into or changing the virtual environment. `pypdf 6.18.0` was installed into `%TEMP%/voxpilot-m6-test-deps` and made available through `PYTHONPATH` for verification. The application's normal environment still needs the newly declared dependency before PDF extraction can work there.

Final focused command:

```powershell
$env:PYTHONPATH = Join-Path $env:TEMP 'voxpilot-m6-test-deps'
.\.venv\Scripts\python.exe -m pytest tests/test_documents.py tests/test_document_process.py tests/test_document_ui.py tests/test_document_ollama.py tests/test_tts.py -q --tb=short
```

**114 passed in 4.07 seconds**, no failures or skips. This includes the existing TTS tests plus the new PDF and Stop regressions.

Final complete suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

**489 passed in 6.25 seconds**, no failures or skips. The previous suite contained 382 tests; 107 additional tests now pass.

`git diff --check`: passed. Git reports normal LF-to-CRLF conversion notices for edited tracked files; no whitespace errors.

Application launch smoke check: **passed**. The actual `app.main.main()` entry point launched offscreen with a temporary synthetic PDF, temporary approved roots/settings/SQLite database, mocked microphone enumeration and mocked Ollama output. It used the real isolated parser, real command worker, real Qt event loop and MainWindow. The summary appeared, the history database remained empty for the document task, and application shutdown succeeded. Output contained only a timing/cancellation log and a PASS marker, no PDF contents.

No real microphone, user documents or live Ollama model were used by automated verification. Live voice/model acceptance remains a manual check; it is not represented as passed.

## Files created

- `app/documents/__init__.py` — document module boundary.
- `app/documents/policy.py` — strict typed arguments and approved document-root identifiers.
- `app/documents/routing.py` — deterministic summarize/locate phrase matching.
- `app/documents/limits.py` — validated configurable resource limits.
- `app/documents/process.py` — killable parser processes and Windows memory isolation.
- `app/documents/extraction.py` — bounded search, file identity checks, read-only extraction and normalization.
- `app/documents/summarizer.py` — page-aware chunks, dedicated text-only prompt, output validation and bounded final synthesis.
- `app/documents/service.py` — orchestration, expiring one-use selections, safe results and buffer release.
- `tests/test_documents.py` — schemas, routing, PDF validation, extraction, chunking, injection and privacy tests.
- `tests/test_document_process.py` — real isolated parser, timeout, cancellation and memory-limit tests.
- `tests/test_document_ui.py` — actual Qt signals, selections, responsiveness, wake resumption and stale-worker tests.
- `tests/test_document_ollama.py` — local-only summary transport, payload separation and model-request cleanup.
- `MILESTONE6_VERIFICATION.md` — this report.

## Files modified

- `.env.example` — PDF limits, without changing private `.env`.
- `README.md` — current feature status, usage, architecture, security, limits and limitations.
- `requirements.txt` — `pypdf>=6.18,<7`.
- `app/config.py` — PDF configuration fields.
- `app/main.py` — document service wiring with approved roots and the configured local primary model.
- `app/models.py` — document states, selection data and separate short spoken response.
- `app/agent/router.py` — deterministic document matching before planner fallback.
- `app/agent/schemas.py` — allowlisted `summarize_pdf` and `locate_pdf` structured intents.
- `app/agent/intent_planner.py` — document target/root grounding checks.
- `app/agent/ollama_client.py` — summary-specific payload using the existing bounded local transport.
- `app/agent/executor.py` — validated document dispatch, cancellation and selection invalidation.
- `app/security/policy.py` — document tool allowlist.
- `app/security/validators.py` — PDF argument validation.
- `app/tools/registry.py` — updated help and guarded document-pipeline boundary.
- `app/ui/workers.py` — progress signals, document selection execution and GUI-thread identity relay.
- `app/ui/main_window.py` — progress display, selection controls, voice selection, short speech and stale-result guards.
- `app/voice/tts.py` — Stop drains queued speech and interrupts native speech, including startup races.
- `tests/test_tts.py` — cancellation during native speech-process startup.

## Validation and execution architecture

Typed/transcribed command → deterministic router → optional local intent planner → strict tool/argument validation → document service. The shared command QThread performs orchestration. Search and PDF parsing run in short-lived isolated processes. The same Ollama transport performs cancellable local-only model requests in separate processes. There is no new arbitrary browser, shell, executable or file-write tool.

Public document tools are `summarize_pdf` and `locate_pdf`. Extraction is deliberately internal, not an independently routed tool that could expose raw document text. Stop and `Cancel PDF summarization` are local lifecycle operations rather than model-selected filesystem tools. `Show information about report.pdf` retains the existing metadata-only `file_info` route.

Example intent:

```json
{
  "intent": "summarize_pdf",
  "arguments": {
    "root": "documents",
    "query": "resume.pdf",
    "summary_style": "concise"
  },
  "confidence": 0.96,
  "requires_confirmation": false
}
```

Pydantic rejects extra fields, incorrect types, unsupported styles and unsafe names. Query is a 1–120-character safe filename/name fragment, never a path or URL. Styles are concise, detailed or bullet_points. Allowed roots are desktop, documents, downloads, approved project_N identifiers, and `all` as an internal search scope over just those roots. Runtime root approval remains authoritative, including for syntactically valid but unapproved project identifiers. Existing confidence, request-grounding and security checks remain in force.

Multiple matches produce an opaque, one-use selection token held in application memory and a numbered logical-root/relative-name list. A button, typed number or session-bound manual voice selection chooses an exact entry. Timeout, an unrelated command, Stop and closing invalidate the selection. Stale voice or worker signals cannot select a newer file or replace its result.

## PDF validation and limits

- Reuse Milestone 5 canonical root resolution and sensitive-path/link checks. Search never descends through symbolic links or junctions. Link tests simulate OS flags so administrator privileges are unnecessary.
- Validate regular file, case-insensitive extension, `%PDF-` signature, local approved containment and selection identity. Revalidate immediately before opening and compare the opened handle's identity; check again after extraction.
- File identity uses device, inode/file ID, size and last-write time. Python 3.12 Windows path-stat and handle-stat can disagree about `ctime`; including it caused false change detections and was corrected.
- Open read-only binary handles. Never invoke PDF viewers, JavaScript, embedded attachments, launch actions or hyperlinks. Encrypted/password-protected files are rejected without attempting decryption.
- Default file/page limits: 20 MB / 100 pages, checked before extracting pages. Empty, malformed, inaccessible, changed and missing files return safe errors.
- Default output limits: 200,000 extracted characters; 20,000 characters per page. Stop when either limit is reached and mark truncated summaries.
- Search: four directory levels, 10,000 visited entries, at most 20 matching candidates. Explicit requests exceeding result/entry limits fail and ask for a narrower query.
- Windows Job Object process memory cap: 512 MB by default, set before parsing. A Linux resource-limit implementation supports isolated testing elsewhere, but Windows 11 remains the target. Failure to establish isolation rejects processing.
- Search/extraction wall deadline: 60 seconds per process. Cancellation/timeout terminates and joins the process, including if native parsing is stuck within a page.

## Extraction, summarization and injection protection

Extract sequentially with page numbers. Remove null/control characters and normalize whitespace. Record empty processed pages. Text below the configured minimum (default 20 alphanumeric/word characters) is insufficient for a reliable summary and returns the scanned/image-based OCR limitation message. Extraction exceptions are failures, not silently empty documents.

Chunks preserve page order and prefer page boundaries, splitting long pages when necessary. Default maximum: 20 chunks of 10,000 characters including labels. Each chunk is summarized independently; exactly one final synthesis uses the ordered intermediate summaries. Intermediate output is capped so synthesis input stays bounded. Truncation at any of these boundaries is disclosed. There is no recursive summarization. Partial model failures never become completed summaries.

The summarizer's dedicated system prompt labels document text as untrusted data and instructs it to ignore embedded commands. The user payload uses JSON framing, including for intermediate summaries. No tool list, tool-call schema, private configuration, environment variables or resolved source paths are provided. The only capability is returning text. Validation rejects structured tool requests, JSON, markup, code fences, unsafe controls and oversized/empty output. MainWindow uses plain-text rendering. Output is never sent to the router, registry or executor. Prompt injection cannot grant execution capability.

Ollama remains bound to localhost/loopback with proxies and redirects disabled. Local model metadata is checked before sending text; remote/cloud aliases are rejected. Every model request observes cancellation and the remaining total summarization budget (180 seconds by default). Timeout or unavailability gives a recoverable message.

## UI, voice and privacy

Document states and page/chunk progress use Qt signals with a GUI-thread relay that validates current worker identity, cancellation and application closing. The active command-thread guard prevents duplicate document workers. Completed summaries remain visible after real wake-worker restart; listener states update Status only. Wake input remains exact normalized Hello and never reaches Ollama. Microphone locking, shared Whisper, allowlists and TTS cooldown are preserved.

Spoken output is optional and limited to the overview (300 characters by default). It cannot read the full summary. Stop handles parser/model cancellation, clears pending selections and drains/cancels native TTS. It retains the existing behavior of disabling wake mode; successful/failed tasks resume enabled wake mode after TTS/cooldown.

PDF tasks opt out of history entirely in this version, preserving the existing ordinary command history behavior. Neither extracted text nor full/partial summaries are written to SQLite. Parser diagnostics are suppressed in the disposable process; application logs contain metadata/timing only. Buffers/containers are cleared and references released in completion/failure/cancellation paths. No temporary extracted-text files are created. Immutable Python strings and operating-system paging cannot guarantee forensic memory erasure.

The final automated output and application smoke output contained no extracted PDF text. `git diff --cached --name-only` was empty: no private environment, virtual environments, PDFs, extracted text, database or temporary artifacts were staged. `.env`, `.venv` and `venv` were not modified by this work.

## Manual acceptance checklist — not claimed as executed

1. Supply pypdf in the runtime environment and start the configured local Ollama model. Use a disposable, text-based PDF in an approved Documents folder.
2. Type `Summarize test.pdf in Documents`. Confirm locating/extraction/chunk progress and a readable filename, overview, main points and factual details.
3. Leave the application idle and enable wake mode. Confirm the full result remains while Status becomes Wake-word listening.
4. Say Hello, wait for the acknowledgement and cooldown, then say the PDF command. Confirm only the command after Hello is processed and the summary stays visible on resumption.
5. Repeat with a multipage PDF; confirm page/chunk order, optional short speech and full on-screen summary.
6. Try an image-only PDF; expect the exact OCR-not-available message. Try a missing file; expect a recoverable not-found message.
7. Put matching names in two approved folders. Confirm numbered choices, select by button/typed number/manual microphone, and test expiry.
8. Attempt an outside-root path, traversal or unapproved project identifier; expect rejection. Check that no external viewer or browser opens.
9. Press Stop during locating, extraction, summarization and speech. Confirm prompt cancellation; re-enable wake mode afterward if desired.
10. Stop Ollama temporarily and retry. Confirm a recoverable error and enabled wake-mode resumption after failure. Restart Ollama for subsequent requests.
11. Check history/logs: no document text or full summaries should appear. PDF operations intentionally add no history record.

## Remaining limitations

- Live microphone/TTS, live Ollama quality/latency and real user-folder acceptance are not manually verified in this run; mocks and synthetic PDFs were used.
- The private virtual environment was left untouched. The new pypdf dependency must be supplied to the runtime before normal PDF use; verification used a temporary dependency directory.
- No OCR, encrypted PDF decryption, remote PDFs, embedded-file extraction or document writes. All links/reparse points are conservatively rejected, including some OneDrive/redirected folders.
- Search is bounded and cannot find PDFs deeper than its configured fixed depth. Use a narrower approved project root for deeper files.
- Character limits are not semantic completeness guarantees. Model output can omit or invent facts despite the prompt; important details need human comparison with the document. Injection defenses provide an execution boundary, not a mathematical guarantee of faithful summarization.
- Path/handle identity and repeated policy checks mitigate changes and races but are not an OS security sandbox against another hostile process concurrently manipulating files. OS paging/crash dumps and the separately managed local Ollama daemon are outside application buffer-erasure guarantees.
- Normal history remains intact; PDF tasks currently omit history records rather than persisting optional summary metadata.
