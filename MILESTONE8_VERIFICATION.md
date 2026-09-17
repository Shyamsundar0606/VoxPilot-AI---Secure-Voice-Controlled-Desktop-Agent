# Milestone 8 verification

Dates: 2026-09-16–17. Base commit: `d78c4be` (`Complete Milestone 7 secure project management`). The requested pre-edit `git status --short` was empty and `git log -1 --oneline` matched that commit. AGENTS.md and the existing routing, validation, filesystem, PDF, local-model, project, voice and Qt-worker integration were inspected before implementation.

## Architecture

Typed or transcribed command → deterministic knowledge routing → strict argument policy → KnowledgeService on the existing CommandWorker → approved roots and isolated source operations. The eight public knowledge tools are `index_documents`, `refresh_document_index`, `list_indexed_documents`, `ask_documents`, `search_documents`, `show_answer_sources`, `remove_indexed_document` and `clear_document_index`. Direct registry execution is rejected. Model-proposed intents use the same strict schemas and conservative grounding; deterministic supported phrases are authoritative.

The dedicated `app/knowledge` package separates policy, limits, discovery, extraction, chunking, embedding, local transport, storage, retrieval, answer generation and citation rendering. PDF extraction reuses the existing isolated extractor and parser limits. TXT/Markdown extraction preserves paragraph boundaries and Markdown headings. Raw byte buffers are bounded and overwritten before release; extracted pages are released after chunking.

Document rows contain stable IDs, approved-root IDs, normalized relative names, type, size, nanosecond modification time, filesystem identity, SHA-256 content hash, PDF page count and indexing status. Chunk rows contain document ID, safe relative name, page, heading, sequence, offsets, text and stable hash. A matching rename preserves identity when the old path disappeared and the inode/device and content hash match. Copies remain separate document records. Changed files replace their chunks; successful refresh removes deleted or revoked sources. Embeddings are reused only for unchanged content with the same index configuration signature.

Ollama `/api/show`, `/api/embed` and `/api/chat` calls run in the existing killable process boundary. Transport reuses the existing endpoint/model validation, adds bounded streamed metadata and response parsing, disables environment proxies and redirects, and permits one transient connection/timeout retry inside a wall deadline. No model download endpoint exists. Vector dimensions, finite values and nonzero norms are validated before conversion to normalized little-endian float32.

SQLite schema version 1 stores metadata, chunks and vectors together, with checksums, foreign keys, secure deletion, bounded page/count limits and progress-handler cancellation. A single transaction covers the full indexing operation. Failure/cancellation rolls back changes. Empty databases initialize as version 1; unknown versions and unversioned nonempty databases are refused without modification or automatic migration. No pickle, object deserialization or external vector database is used.

NumPy cosine retrieval is bounded by top-k, similarity, per-document diversity and a total context cap. Duplicate text and overlapping spans are suppressed. Equal scores sort by chunk ID. Sources are revalidated before retrieval and after generation using approval, file identity and complete content hash. Answer requests have separate system instructions and JSON question/evidence data, a strict response schema, and no tools. Citation fields must exactly match retrieved evidence. Generated text is never routed to the executor. Weak evidence returns the fixed insufficient-information message; failed or invalid generation returns excerpts.

Local Knowledge has an explicit source selector, index/refresh controls, counts/progress, question input, answer/source/excerpt panels, cancellation, confirmed clearing and a guarded source opener. Existing project controls remain present. Source labels and answers use plain text. The source opener is a narrow extension of the existing Windows filesystem adapter for PDF/TXT/Markdown; it accepts only an internally retrieved citation and rechecks the source. It is not a general file-opening command.

The existing source-aware CommandSignalRelay rejects stale, cancelled and closing-worker results. One retained command worker prevents duplicate indexing. Wake mode pauses throughout work and selection/confirmation. Local Knowledge Cancel permits enabled wake mode to resume; the existing red Stop retains its behavior of disabling wake mode. Short spoken notifications direct the user to the visible answer/sources. Closing cancels the worker and waits for its completion; isolated processes are terminated and joined.

## Changed files

Added:

- `app/knowledge/__init__.py`, `limits.py`, `policy.py`, `discovery.py`, `extraction.py`, `chunking.py`
- `app/knowledge/transport.py`, `embedding.py`, `storage.py`, `retrieval.py`, `answers.py`, `citations.py`, `service.py`
- `app/ui/knowledge_panel.py`
- `tests/test_knowledge.py`, `tests/test_knowledge_transport.py`, `tests/test_knowledge_ui.py`, `tests/test_knowledge_boundaries.py`
- `MILESTONE8_VERIFICATION.md`

Modified:

- `.env.example`: required knowledge defaults only; `.gitignore`: SQLite sidecar exclusions.
- `README.md`: Milestones 1–8 introduction, setup, commands, policy, local storage and limitations.
- `app/config.py`, `app/main.py`: local knowledge settings and service wiring.
- `app/models.py`: structured knowledge results.
- `app/agent/router.py`, `executor.py`, `schemas.py`, `intent_planner.py`: deterministic routing, dispatch, privacy and strict model-intent grounding.
- `app/security/policy.py`, `validators.py`, `app/tools/registry.py`: eight scoped capabilities, strict arguments and registry bypass rejection; existing application/URL allowlists are preserved.
- `app/filesystem/platform.py`: guarded source-file opening through the Windows adapter.
- `app/ui/main_window.py`, `workers.py`: panel, knowledge worker identity, selections, confirmations, progress and shutdown integration.
- `tests/project_startup_smoke.py`: temporary knowledge settings and assertions for real service/UI construction.

No dependency installation, model download, staging, commit or push was performed. Private environment files, virtual environments, voice-model folders and approved source documents were not modified. Tests use disposable synthetic source folders inside the workspace. Python bytecode writes were disabled for test runs.

## Threat model and security controls

- Untrusted source names, file contents, questions and model responses cannot supply executables, shell commands, raw SQL, unrestricted file targets or tool invocations to the answering pipeline.
- Root containment reuses Windows fixed-drive, path-component, hidden/system and link/junction checks. Discovery skips sensitive names, environment files, dependency/build/log/credential locations and unsupported formats. Explicit selected roots prevent whole-drive or accidental current-directory indexing.
- Read identity is checked against opened handles and resolved paths. Hashing and extraction are bounded and isolated; existing malformed/encrypted/scanned PDF behavior remains in effect. Truncated documents fail instead of silently indexing partial content.
- Local model metadata is checked before content transmission. Requests cannot follow redirects or use proxy environment settings. Bounded output, strict JSON, exact citation checks, and rejection of tool-shaped output/internal-reasoning markers limit model-output abuse.
- The answering client has no execution hooks. Model answers and document instructions are displayed as data, never passed to the router. Synthetic malicious-document tests verify the registry/planner are not invoked.
- Removal/clear proposals bind immutable serialized actions and index revisions to SHA-256 hashes and expiring, single-use tokens. Stop, cancellation, closing, another command, replay, changed revision or changed hash invalidate execution. Only index rows are removed; source files remain untouched.
- Queries, answers, evidence and index operations opt out of SQLite command history. Logs report generic worker failures without source/model content.
- Index content is local but not application-encrypted. Same-user malicious processes, compromised Ollama/Python/native libraries, hostile file associations, operating-system compromise and forensic recovery are outside the enforced boundary.

## Automated verification

Runtime: Windows, Python 3.12.10, using the existing project environment outside the command sandbox. The sandbox alone reported a missing base interpreter; the same executable ran successfully with normal workstation access. No environment repair or installation was needed.

Final focused run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge.py tests/test_knowledge_transport.py tests/test_knowledge_ui.py tests/test_knowledge_boundaries.py -q --tb=short
```

Final focused result: **142 passed in 5.40s**, with no warnings or skipped tests.

Complete regression command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Final complete result: **782 passed, 1 warning in 29.38s**, with no skipped tests. The warning is the existing `audioop` deprecation in the wake-word resampling test; Python 3.12 remains required. This includes all 640 prior regression tests plus 142 Milestone 8 tests.

Standalone startup/shutdown smoke:

```powershell
.\.venv\Scripts\python.exe -m tests.project_startup_smoke
```

Result: **`STARTUP_SMOKE_OK`, exit code 0**. The real app/service graph and Qt window started and closed offscreen using temporary settings and an injected empty audio backend. No real microphone, model load, model request or user source file was accessed. The equivalent startup test is also included in the full pytest suite.

Coverage includes supported command routing; root selection; sensitive names/traversal; link/junction policy; file/page/character/discovery limits; real isolated PDF page extraction; isolated cancellation and timeout termination; deterministic chunks and overlap; incremental changes, copies, renames, replacements and deletions; local transport and bounded retries; invalid/nonfinite/dimension-mismatched vectors; count/storage limits; atomic rollback; corruption and unsupported schema refusal; similarity/diversity/tie ordering; exact citation validation; weak evidence; malicious document instructions and rejected unsafe output; removal/clear expiry/replay/revision binding; ambiguity selection; source revalidation/opening; worker identity, duplicate prevention, responsive cancellation, clean close, and simulated wake/TTS behavior.

An early regression run exposed a local-import placement error in shutdown; it was fixed. Early focused tests also exposed nondeterministic removal-choice ordering and a test-only SQLite connection cleanup error; both were corrected. Final results above supersede those intermediate runs.

`git diff --check` and a separate whitespace check of new untracked Python/Markdown files passed. Git emitted only its existing LF-to-CRLF conversion notices. HEAD remains `d78c4be`, the staging area is empty, and the working tree contains the Milestone 8 implementation and documentation changes only.

## Known limitations and remaining manual checks

- Live Ollama embedding/generation, model-specific answer quality, actual source viewers and acoustic microphone/wake interaction were not exercised. Automated model responses are synthetic. Milestone 7's live npm/Docker checks remain unverified as previously documented.
- A valid citation proves membership in retrieved evidence, not semantic truth or completeness of each answer sentence. Retrieval may miss relevant material. Prompt instructions and output checks cannot mathematically guarantee semantic resistance to every injection, but document/model text has no route to tool execution.
- Index settings/model changes require confirmed clearing and rebuilding; vectors are never silently mixed. Unknown schema versions require an explicit future migration/rebuild workflow.
- One bad document aborts the operation, preserving the prior committed index. Discovery fails on depth/entry/document limits instead of treating an incomplete scan as deletion evidence. Large corpora or slow cold models may exceed deadlines; narrow source folders deliberately.
- Each query hashes current sources in isolated processes, prioritizing freshness over throughput. Limits may need conservative tuning for larger collections. TXT/Markdown have no page citations; PDF normalization follows the existing extractor and does not preserve full layout.
- Index deletion uses SQLite secure deletion but cannot guarantee erasure from disk snapshots, backups, SSD behavior, journals, OS caches or paging. Immutable Python strings cannot be reliably overwritten. The main SQLite file is bounded to 512 MiB; an in-flight rollback journal can temporarily consume additional disk space.
- Same-user filesystem mutation can still race with final source opening. The OS viewer may have its own behavior, plugins or network access. The source opener does not grant the answering model viewer control.
- No OCR, Word/PowerPoint, remote/web indexing, automatic model download, process-wide source sandbox, online fallback or generalized file execution was added.

## Exact manual acceptance procedure

1. Use Windows 11 and Python 3.12. Install the configured local answer model and explicitly run `ollama pull nomic-embed-text`. Start Ollama in local-only mode. Start VoxPilot with `python -m app.main`.
2. Create a dedicated test folder containing only disposable files. Pause wake mode and use **Approve projects folder** to approve that folder; note its assigned `project_N` identifier. Alternatively use the approved Documents root with a dedicated test corpus.
3. Add two text-based PDFs with distinct, verifiable facts on known pages. Do not use private documents. Choose **Load index / sources**, select the approved test source and click **Index documents**.
4. Run **Show indexed documents**. Confirm both safe filenames, indexed status and PDF page counts appear. Observe the progress/count controls remain responsive.
5. Ask a question answered by only one PDF. Confirm the answer cites the expected file and actual page. Select its source row and compare the displayed excerpt with that page.
6. Ask an unrelated question. Confirm insufficient evidence rather than an unsupported answer. Test model unavailability separately and confirm retrieved excerpts remain available when generation fails.
7. Add a TXT file containing explicit malicious instructions to run a shell, read a secret, override policy and contact an external host. Refresh the index, ask about that document, and confirm no tool, shell, file read or external request is performed by the answering pipeline.
8. Change one PDF and refresh. Confirm the update reports only the changed document as embedded and unchanged documents reused. Rename a source and refresh; confirm its identity/citations update without unnecessary embedding.
9. Delete one disposable source, refresh, and confirm it and its chunks are gone. Change or remove another source without refreshing; confirm stale excerpts are not returned.
10. Start indexing a sufficiently large synthetic corpus and press Local Knowledge **Cancel** during embedding. Reload the index and confirm the previously committed index remains intact, without partial new document/chunk rows.
11. Ask a supported question and run **Show sources for the last answer**. Confirm the same current files/pages appear. Use **Open selected approved source** and verify the expected viewer opens only that cited PDF/TXT/Markdown file. Repeat after replacing/deleting the source and confirm rejection.
12. Put two disposable files with the same basename in different allowed subfolders. Request removal by basename, verify numbered choices, select one, reject confirmation and confirm both remain indexed. Repeat and approve; confirm only the chosen indexed document is removed, with original files unchanged.
13. Request **Clear the document index**, say **No**, and confirm index contents remain. Repeat and allow the 30-second token to expire; **Yes** must not clear it. Request again and say **Yes**; confirm indexed count becomes zero and all original documents remain untouched.
14. Reindex. Enable wake mode, say **Hello**, wait for acknowledgement and say **Ask my documents what the report says about cloud security**. Confirm only the question reaches retrieval, a short notification is spoken, wake listening resumes and the answer/sources remain visible.
15. Cancel a knowledge task while wake mode is enabled; verify Local Knowledge **Cancel** resumes enabled wake mode after completion. Verify red **Stop** retains its documented wake-disable behavior. Verify manual microphone input and other approved commands still work.
16. Close the application during indexing and during generation. Confirm it exits after cancellation, leaves no knowledge child process/Qt worker, and the next launch can open the prior committed index. Recheck existing project-management controls and separate process-output panel.

These live steps remain for user acceptance; automated tests are not a substitute for the live checks above.
