# Milestone 5: secure local files and folders

## Result

Implemented five approved tools: `open_folder`, `list_directory`, `find_file`, `create_folder`, and `file_info`. Deterministic routing remains first; local intent planning is limited to structured, validated variations. No file contents are read. The only operation that writes user data is creating a new folder after explicit confirmation. Project approval updates the application's own root settings.

## Created files

- `app/agent/file_routing.py`
- `app/filesystem/__init__.py`
- `app/filesystem/platform.py`
- `app/filesystem/roots.py`
- `app/filesystem/service.py`
- `app/security/confirmations.py`
- `app/security/filesystem_policy.py`
- `tests/test_filesystem.py`
- `tests/test_file_confirmations.py`
- `tests/test_file_ui.py`
- `tests/test_filesystem_process.py`
- `MILESTONE5_VERIFICATION.md`

## Modified files

`.env.example`, `README.md`, `app/agent/executor.py`, `app/agent/intent_planner.py`, `app/agent/ollama_client.py`, `app/agent/router.py`, `app/agent/schemas.py`, `app/config.py`, `app/main.py`, `app/models.py`, `app/security/policy.py`, `app/security/validators.py`, `app/tools/registry.py`, `app/ui/main_window.py`, and `app/ui/workers.py`.

## Architecture and approved roots

`filesystem_policy.py` contains strict typed schemas and lexical path policy. Separate schemas validate root/path, listing options, file search and folder creation. Root identifiers are logical names; models cannot supply absolute paths. Model output remains strict JSON, with extra fields rejected.

`ApprovedRoots` resolves Windows Known Folders through an injectable `WindowsFolders` adapter. The six built-in roots are Desktop, Documents, Downloads, Pictures, Music and Videos. Every root must be an existing directory on a fixed local drive. The UI's **Approve project folder** action validates a selected directory in a worker and persists a `project_N` identifier in application settings. Models cannot register roots.

The service canonicalizes each path, checks containment, rejects sensitive components and every symlink/junction/reparse point, and revalidates before opening, metadata access or creation. Virtual environments with `pyvenv.cfg` or `conda-meta` are rejected even with nonstandard names. Hidden and system entries are omitted. Recursion never intentionally follows links.

Operations run through the existing Qt command-worker pattern. Production filesystem operations use a disposable child process with a five-second wall timeout, allowing Stop to terminate a blocked operation. The default depth cap is four and result cap is 100; searches default to 20 results. Limits are configurable with hard caps. Returned names are relative to approved roots, with truncation stated. Rootless name searches cover approved roots; unqualified file-information commands default to Documents.

## Confirmation design

Creation first performs a read-only validation and returns the exact parent and proposed name. An opaque, one-use token binds an immutable request to the canonical parent and its filesystem identity. The token expires after 30 seconds by default. `requires_confirmation=false` from the model is forcibly changed to true for creation. Registry dispatch of `create_folder` only prepares a proposal and cannot write.

The confirmation panel has Confirm and Cancel buttons. The manual microphone flow accepts exact normalized Confirm or Cancel and binds the response to the proposal active when recording began. Stale responses cannot confirm a newer proposal. The backend consumes the token once and revalidates the parent and destination before `mkdir(exist_ok=False)`.

A new unrelated command, Cancel, expiry, Stop or close invalidates the proposal. Wake listening pauses while it is pending. Listening resumes after confirmation, cancellation or expiry if wake mode is still enabled; Stop preserves the previous behavior of disabling wake mode entirely.

## Security and privacy

The existing tool/application/URL allowlists remain authoritative. Filesystem tools reject traversal, control characters, nulls, absolute/device/UNC/network paths, alternate streams, reserved Windows names, trailing dots/spaces, drive roots, removable drives, sensitive directories and linked paths. No delete, rename, copy, move, overwrite or file-execution tool exists. Model-generated commands and code are never executed.

Directory listings and filesystem results are not persisted in command history. Logs contain tool names and timing, not paths or names. UI errors are generic or policy-specific without OS path details; the exact parent is deliberately visible in the confirmation panel. No directory listing or file contents are sent to Ollama. Existing non-filesystem history and TTS behavior remain intact; filesystem TTS uses a short summary instead of speaking whole listings.

## Verification

Runtime: existing Python 3.12.10 interpreter; no package installs or virtual-environment edits.

- Focused: `python -m pytest tests/test_filesystem.py tests/test_file_confirmations.py tests/test_file_ui.py tests/test_filesystem_process.py -v` — **78 passed**.
- Complete: `python -m pytest -v` — **378 passed**.
- Tests use temporary workspace sandboxes and mocked folder openers/platform or process boundaries. Real user folders are not opened or modified. Qt integration tests exercise actual command-worker completion, confirmation buttons, expiry, stale voice responses and work off the GUI thread.
- Final Git whitespace and staging checks are recorded in the task response. No commit or push was requested or created.

## Manual acceptance steps

1. Restart VoxPilot to load Milestone 5. Type `Open my Documents folder`; confirm the approved Documents folder opens.
2. Type `Show files in Downloads`; verify readable results, hidden entries omitted and truncation reported when applicable.
3. Type `Find my resume in Documents`; verify only visible matches within the approved root/depth. Try `Show information about resume.pdf in documents` for basic metadata.
4. Request `Create a folder called VoxPilot Test in Documents`. Check the exact parent/name in the panel, select Cancel and verify it was not created.
5. Repeat, explicitly Confirm and verify one new folder exists. Repeat again and verify an existing destination is rejected.
6. Test expiry and a new unrelated command while a proposal is pending. Confirm neither can leave an old proposal usable.
7. Request AppData, `.ssh`, `.git`, a virtual environment, a traversal path or a UNC location; verify rejection and no external action.
8. Press Stop during a search and while confirmation is pending. Confirm cancellation and wake-mode disabling.
9. Enable wake mode, say Hello, then issue a folder command. Verify wake listening resumes after completion or Cancel/expiry. For voice approval, use Microphone to say exactly Confirm or Cancel while the panel is active.
10. With listening stopped, approve a non-sensitive project folder and use the returned `project_N` identifier. Restart and verify its saved root remains available.

## Remaining limitations

Real Windows user-folder and spoken acceptance checks have not been performed. Reparse points are conservatively rejected even when they lead inside an approved root, which can exclude redirected or OneDrive-backed folders. Search order follows the filesystem and is not sorted before truncation. There is no file-content search and no opening of individual files. Unqualified file-info commands use Documents rather than guessing among multiple matching files.

Path revalidation and parent-identity checks narrow race windows but are not an OS sandbox against a hostile local process concurrently altering the filesystem between the last check and OS dispatch. A cancellation or timeout racing with an already-dispatched `mkdir` cannot undo that write; inspect the proposed destination before retrying. No rollback deletion is performed. Approval settings registration runs in a Qt worker; the hard child-process timeout applies to the five filesystem tools.

Private `.env`, `.venv`, and `venv` were not modified. No commit was created.
