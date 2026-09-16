# Milestone 7 verification

Date: 2026-09-13. Base commit: `92f5572`. Runtime: Windows, Python 3.12.10, pytest 8.4.2.

## Implemented architecture

Typed/manual/wake-initiated command → deterministic router → optional local intent planner → authoritative tool validator → project service → approved-root resolution. Discovery is metadata-only, bounded and isolated in a cancellable child process using the existing process-isolation helper. Only saved `project_N` roots are scanned.

The six public tools are `list_projects`, `open_project`, `get_project_info`, `start_project`, `list_running_projects`, and `stop_project`. Strict schemas reject extra fields, executable arguments, paths and PIDs. Model output cannot define launch profiles or bypass confirmations. A project name must be grounded in the user's request; ambiguity produces numbered, expiring choices.

The profile service validates explicit local configuration before saving and again before executing. Python module/script, fixed npm script, and restricted Docker Compose plans use fixed argument arrays. Start plans contain canonical project/cwd paths, executable, fixed arguments, safe environment, profile, file identities and entry/manifest hashes. The confirmation service holds an immutable serialized plan and SHA-256 hash, with a single-use token and deadline. Confirming consumes the token before action; a changed profile/file, mismatched hash/token, expiration or cancellation rejects it. Stop plans bind the internal tracked instance, project id, PID and start time; names are never converted to arbitrary PIDs.

A private, hidden supervisor owns each newly created Windows Job Object. Its single-threaded CreateProcess wrapper creates the project suspended, assigns it to the job, and resumes it only after successful assignment. Python/npm graceful stopping sends CTRL_BREAK to the owned process group; the timeout fallback terminates only that job. Docker uses a fixed local named-pipe endpoint, a unique internal Compose project name and a reviewed in-memory manifest snapshot for both start and stop. Failed Docker termination is not reported as successful.

Supervisors drain merged stdout/stderr into bounded in-memory buffers without reader threads. Completed buffers expire, parent snapshots are discarded, and UI output has a retention timer. Closing the UI detaches its pipes without terminating launched projects; supervisors discard output and exit when their trees end. No project-management thread remains in the UI. Session tracking deliberately cannot reattach to a previous session's processes.

The project UI includes root approval, refresh, selector, type/state, open/start/stop, validated profile saving, full confirmation details and a separate read-only output panel. Commands, discovery, profile validation and process operations use the existing QThread command-worker pattern. Relays check worker identity, explicit source, cancellation and close state. Pending confirmations pause wake listening; exact confirmation replies are intercepted before normal routing. Wake resumption updates Status without replacing the command result.

## Files changed

Created:

- `app/projects/__init__.py`
- `app/projects/policy.py`
- `app/projects/discovery.py`
- `app/projects/profiles.py`
- `app/projects/platform.py`
- `app/projects/output.py`
- `app/projects/supervisor.py`
- `app/projects/processes.py`
- `app/projects/service.py`
- `tests/test_projects.py`
- `tests/test_project_ui.py`
- `tests/test_project_processes.py`
- `tests/project_startup_smoke.py`
- `MILESTONE7_VERIFICATION.md`

Modified:

- `.env.example` — documented bounded project settings.
- `README.md` — approval/profile setup, runner examples, lifecycle and limitations.
- `app/config.py` — project limits and local profile-store location.
- `app/main.py` — project-service wiring.
- `app/models.py` — project result data and project-selection status.
- `app/agent/router.py` — deterministic project commands before other routing/model fallback.
- `app/agent/schemas.py` — six strict project intents.
- `app/agent/intent_planner.py` — grounded project targets and mandatory start/stop confirmation.
- `app/agent/ollama_client.py` — project schema instructions without launch parameters.
- `app/agent/executor.py` — authoritative project-service dispatch and invalidation.
- `app/security/policy.py` — tool allowlist and confirmation-required tools.
- `app/security/validators.py` — strict project argument validation.
- `app/tools/registry.py` — prevent direct registry bypass of project execution.
- `app/ui/workers.py` — project sources, confirmation/selection/profile operations and relay checks.
- `app/ui/main_window.py` — project management, confirmation interception, output retention and shutdown.

No dependency installation was needed. `.env`, `.venv`, `venv`, and `D:\VoskModels` were not modified. No stage, commit or push was performed.

## Security controls

- Reuses existing canonical-path, traversal, hidden/system, symlink and junction protections; no automatic current-directory trust.
- Discovery bounds depth, visited directories, per-directory entries, result count and wall-clock time. Hidden/cache/dependency/build folders are skipped.
- Local native executables must exist, match the runner's expected executable name and pass local-drive/reparse checks. A project-local interpreter is an explicit executable-only exception; file tools cannot browse its virtual environment.
- No shell execution API, `shell=True`, generated command strings, eval/exec, or automatic dependency installation is introduced.
- npm requires an existing script key, validated Node/npm CLI pairing, no arbitrary npm arguments and no automatic pre/post hooks.
- Compose accepts only JSON syntax within approved YAML filenames, services with digest-pinned images and optional Boolean init/read_only. Other options—including privileged mode, mounts, ports, builds and environment files—are rejected. No network image pull is performed.
- Profiles and tool arguments remain separate schemas. Model requests cannot supply profiles, executable/cwd paths, command arguments, environment values or process IDs.
- Inheritance is restricted to the documented safe environment-name allowlist. Sensitive names and startup-injection variables are rejected. Project operations and output are excluded from SQLite history; logs record decisions without prompt/profile/output content.
- Process ownership uses handles/Job Objects, not a user-provided PID. Duplicate launches are blocked by default. Red Stop cancels VoxPilot work without implicitly killing launched projects.
- Existing voice, URL, filesystem and PDF security implementations were preserved and their regression tests passed.

## Verification results

Final focused command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_projects.py tests/test_project_ui.py tests/test_project_processes.py -q --tb=short
```

**98 passed in 8.26s.** No skipped tests or warnings in this run.

Final complete suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

**640 passed, 1 warning in 25.94s.** The warning is the existing `audioop` deprecation in the wake-word resampling test; Python 3.12 remains the supported runtime.

The real application entry point was launched offscreen with temporary settings, the real UI/service graph and an injected empty audio backend. It returned `STARTUP_SMOKE_OK`, exited successfully and left no VoxPilot audio worker thread. The smoke test is included in the 98/640 counts; its separate run was **1 passed in 2.01s**. No real microphone, Ollama request, speech model load or private configuration was used.

Real Windows process tests launched only disposable synthetic Python fixtures. They verified graceful stopping, forced stopping of a CTRL_BREAK-resistant process, descendant-tree termination, exclusion of an unrelated controlled fixture, duplicate prevention, and detachment leaving a finite fixture alive until its natural exit. All fixture processes were cleaned up. No actual user project, npm application or Docker container was launched.

Two earlier test-only timing failures were resolved by waiting for the actual Qt close/worker-finished conditions while releasing the Python GIL. The final focused and complete runs above passed.

Whitespace verification: `git diff --check` and checks of new untracked files passed. The index remained empty and HEAD remained `92f5572`.

## Limitations and unverified manual checks

- Live Explorer opening, approval of the user's actual project root, actual project profiles, acoustic wake/voice interaction, installed npm and live Docker execution remain manually unverified.
- Compose support is intentionally a narrow JSON-syntax subset; ordinary unrestricted YAML Compose files will be rejected. Docker daemon outages may leave containers requiring manual inspection and are not reported as confirmed termination.
- Project code, npm scripts, interpreters and images are trusted after explicit approval and run with the user's Windows permissions. This is not a sandbox or a source-code audit. Transitive source dependencies are not recursively hashed; concurrent hostile local filesystem modification cannot be completely eliminated.
- Metadata/profile/entry reads are capped at 64 KiB; discovery limits can omit deeper or very wide projects. One profile per discovered directory is currently required for starting. Rust and Go are discovered/opened but have no inferred launcher.
- Process output refresh is explicit, not continuous. Output redaction is conservative/best-effort for arbitrary project text; applications should not print secrets. Immutable Python strings cannot promise cryptographic erasure.
- Tracking is session-only (maximum 100 instances). Closing the UI intentionally leaves launched projects running. A new UI session cannot attach to them; use the application's own controls or Docker tooling after detachment. An unexpected supervisor failure is reported as unavailable, not as a successful stop.
- Python 3.12 on Windows is required for the native process boundary; other OSes are not supported by the project launcher.

## Manual acceptance procedure

1. Launch VoxPilot on Windows 11 with Python 3.12. Pause wake mode and use **Approve projects folder** to approve the intended project parent (for this workstation, the user-requested `D:\shyam\Projects`). Confirm that only the resulting `project_N` root is scanned.
2. Refresh projects. Check deterministic names/types/relative locations and absence of `.git`, virtual environments, node_modules and build output. Verify a Unicode project name works and ambiguous names show numbered choices.
3. Select a project and use **Open project**. Confirm only its approved folder opens in Explorer.
4. Review the project's code and create one explicit profile using **Save launch profile** and the README examples. Use the actual installed Python/Node/Docker executable and the correct approved-root identifier. Confirm no process starts merely from saving.
5. Request start. Review name, directory, runner, executable, full fixed argument array and cwd. Say **No**; verify nothing starts. Repeat and allow the confirmation to expire; verify **Yes** no longer starts it.
6. Request again and say **Yes**. Confirm one project instance starts. Request another start and verify duplicate rejection. Use **Show running projects** / **Refresh process output** to inspect its state and bounded output.
7. Request stop, reject it, and confirm the project remains running. Request again, approve, and verify only that tracked tree stops. For Docker, verify its uniquely named Compose containers stop and any daemon failure is reported rather than silently accepted.
8. Attempt traversal, unknown executable parameters, arbitrary shell syntax, an untracked PID and an unsafe Compose option. Verify rejection without side effects.
9. Enable wake mode and repeat a project request. Confirm “Hello” remains activation-only, acknowledgement precedes one command capture, confirmation pauses wake, and listening resumes after completion/failure/cancellation when enabled. The completed result must stay visible.
10. With a harmless project running, press red Stop and confirm the project is not killed. Close VoxPilot and confirm the documented leave-running behavior; stop that project using its own controls afterward. Verify no UI worker threads remain.
