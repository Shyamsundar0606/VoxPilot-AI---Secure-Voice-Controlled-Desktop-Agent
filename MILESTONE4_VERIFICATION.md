# Milestone 4: local intent planning

## Google search extension

Added allowlisted `search_google` with exactly one argument, `query`. It constructs only `https://www.google.com/search?` plus `urlencode({"q": query})` through WebTools' existing browser opener. The model cannot specify a URL, domain, scheme, executable or additional arguments. Queries are nonempty strings, at most 300 characters, with controls, line separators and URL/scheme input rejected. Shell-like punctuation remains encoded query data.

The four clear phrases (`Search Google for EPITA`, `Google EPITA`, `Open Google and search for EPITA`, `Find EPITA on Google`) use deterministic routing. Invalid deterministic queries fail policy validation without model fallback. Unmatched natural requests can use the existing local planner, with validated query text required to appear in the original request. Existing `Open Google` behavior and all other policy checks remain intact.

Files changed for this extension: `app/security/policy.py`, `app/security/validators.py`, `app/tools/web_tools.py`, `app/tools/registry.py`, `app/agent/router.py`, `app/agent/schemas.py`, `app/agent/ollama_client.py`, `app/agent/intent_planner.py`, `README.md`, this report, and new `tests/test_google_search.py`.

Verification: `python -m pytest tests/test_google_search.py tests/test_router.py tests/test_web_tools.py tests/test_llm_security.py -v` — **126 passed**. `python -m pytest -v` — **300 passed**. `git diff --check` passed with only line-ending conversion notices. Browser actions were mocked. No private environment or virtual environment files were changed, and no commit was created. Restart the running app and try `Open Google and search for EPITA` for manual browser verification.

## Implementation

Partial Milestone 4 changes were already present when this task started and were preserved, reviewed and completed. No commit or push was made.

New files relative to Git: `app/agent/intent_planner.py`, `app/agent/schemas.py`, `tests/test_intent_planner.py`, `tests/test_ollama_client.py`, `tests/test_llm_security.py`, `tests/test_intent_runtime.py`, and this report.

Modified files: `.env.example`, `README.md`, `app/agent/executor.py`, `app/agent/ollama_client.py`, `app/config.py`, `app/main.py`, `app/models.py`, `app/ui/main_window.py`, `app/ui/workers.py`, `app/voice/voice_controller.py`, and `tests/test_ollama.py`.

The command worker invokes the executor off the GUI thread. The executor consumes exact normalized Hello, tries deterministic routing, and calls IntentPlanner only for unmatched text. Voice preparation defers planning to that same worker. A validated plan maps public intent names to the existing tool names and passes executor and registry policy checks before dispatch. Existing allowlisted commands do not depend on Ollama.

The strict schema requires exactly four fields: intent, arguments, confidence and requires_confirmation. Seven literal intent names are allowed. Arguments must match the exact keys and approved values for that tool. Extra fields, invalid types, duplicate JSON keys, nonfinite numbers, malformed JSON and unknown names are rejected. Confidence defaults to a minimum of 0.85. Confirmation-required requests are rejected, never auto-approved.

The client uses a local loopback HTTP endpoint, disables environment proxies and redirects, verifies local model metadata, bounds chat response size, and applies an 8-second wall timeout. A disposable HTTP worker process makes cancellation bounded without leaving a blocked network thread behind. Stop and closing the UI signal cancellation; completion cannot launch a tool after cancellation has been observed.

Security is independent of the model: prohibited input filtering, single-action checks, a recognizable target, strict schema validation, and existing tool/application/URL allowlists. No model-generated shell, code, executable path or URL is executed. Free-form requests are replaced with canonical action names or a generic label before history storage. Logs contain validated intent names, acceptance status and timing, not prompts or model response details.

## Verification

Python 3.12.10 was used through the existing `.venv/Scripts/python.exe`; no virtual environment or private `.env` was edited.

- Focused: `python -m pytest tests/test_intent_planner.py tests/test_ollama_client.py tests/test_llm_security.py tests/test_intent_runtime.py -v` — **72 passed**.
- Complete: `python -m pytest -v` — **250 passed**.
- Tests use mocked model, HTTP, process, microphone, application and browser boundaries. They exercise policy rejection, privacy, fallback order, timeout, cancellation and Qt responsiveness. Existing wake signal tests also pass.
- Application launched with `python -m app.main`. Startup logs confirmed the shared Whisper model uses CPU/int8. Saved wake mode began listening. This is startup verification, not proof of a successful live Ollama command.
- `git diff --check` passed (only CRLF conversion notices). The staging area is empty. No commit was created.

## Manual verification

1. Ensure local Ollama is running with cloud disabled and `llama3.2:3b` installed. Warm the model if needed. Restart VoxPilot to load the current code.
2. Type `Open Spotify`. Confirm normal deterministic execution; it must work with Ollama stopped as well.
3. With Ollama running, type `Could you bring up Spotify please?`, then `Launch my browser please`. Confirm only Spotify and Chrome respectively open, and history contains a canonical approved action rather than the raw prompt.
4. Try `Can you check the time?`, `What date are we on?`, `How much battery remains?` and `How much free disk space remains?`.
5. Try deletion, PowerShell, arbitrary executable paths, arbitrary URLs and instruction-override requests. Confirm rejection and no external action.
6. Stop Ollama and submit a natural variation. Confirm a recoverable unavailable message; then verify an exact time command still works.
7. Start a natural request and immediately press Stop. Confirm cancellation, responsive controls and no delayed execution. Repeat while closing the app.
8. Enable wake mode, say `Hello`, wait for acknowledgement/cooldown and command listening, then say a natural Spotify request. Confirm Hello never enters history and listening resumes after the second command.

## Remaining limitations

Live Ollama output quality and spoken end-to-end acceptance were not verified in this task. Small local models can misclassify requests; strict policy prevents unapproved tools but cannot prove that every approved interpretation matches the user's intent. Confidence is model-reported, not a calibrated probability. Conservative filtering rejects some harmless wording, multi-action requests, negation and ambiguous targets. Cold model loading may exceed the short timeout. Stop cannot reverse an already dispatched safe OS operation. VoxPilot does not control logging settings of a separately managed Ollama server.
