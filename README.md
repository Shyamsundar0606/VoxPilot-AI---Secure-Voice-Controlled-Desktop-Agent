# VoxPilot AI

VoxPilot AI is a local-first Windows desktop assistant. Its voice identity is **Shyam**. The project aims to make common laptop actions accessible through natural language while keeping execution deterministic, restricted, and private.

Milestones 1–8 provide safe desktop tools, local speech recognition, exact "Hello" wake activation, local intent planning, approved-folder operations, local PDF summarization, approved project management, and local document indexing with citation-based question answering.

## The problem

General-purpose automation can turn generated text into unsafe operating-system commands. VoxPilot instead routes recognized phrases to a small allowlist of reviewed tools and fixed application identifiers. Unknown requests are rejected rather than guessed.

## Current features

- Dark PySide6 desktop interface titled **VoxPilot AI**, with **Shyam** as the assistant
- Typed commands and click-to-record microphone commands with safe Stop controls
- Idle, Listening, Processing, Completed, and Failed status model
- Command, result, and SQLite-backed history panels
- Background command execution and background `pyttsx3` speech
- Spoken-response toggle and graceful error handling
- Deterministic command router; Ollama is optional and never required for supported commands
- Mockable Windows tool layer for time, date, battery, storage, approved applications, approved URLs, and help
- Input-device selection, refresh/test controls, audio-level display, silence detection, and bounded recording
- Local faster-whisper transcription with structured confidence and error validation
- Continuous local Vosk wake detection with an exact finalized phrase and exclusive microphone ownership
- Read-only PDF extraction and local summaries with bounded resources, explicit file selection and cancellable progress

## Architecture

`app/ui` contains presentation and retained Qt workers. `app/agent` routes and executes requests. `app/tools` contains approved desktop actions. `app/security` validates tool names and arguments. `app/filesystem` resolves approved local roots. `app/documents` isolates PDF search/extraction and text-only summarization. `app/database` persists ordinary command history. `app/voice` separates device discovery, in-memory recording, local transcription, routing coordination, and text-to-speech. Typed Pydantic models carry requests and results between layers.

## Technology

Python 3.12, PySide6, Pydantic, pypdf, psutil, pyttsx3, Vosk, faster-whisper, sounddevice, NumPy, requests, platformdirs, SQLite, and pytest. No paid service, API key, Docker, or administrator access is required.

## Security design

- Tools and applications are allowlisted; application launch data comes only from fixed source mappings.
- Arbitrary paths, shell commands, PowerShell, `eval`, and `exec` are never accepted.
- Unsupported, sensitive, and destructive commands fail safely.
- URLs are selected by approved symbolic names.
- Ollama JSON is schema-validated and policy-validated before it can become a tool request.
- History stores command outcomes but no credentials or secrets.
- Audio is processed locally in memory and is not uploaded or saved.
- Transcribed speech must pass through the same deterministic allowlist as typed commands.

## Supported commands

- Time: `What time is it?`, `Tell me the time`
- Date: `What is today's date?`
- Applications: Chrome, Spotify, Windows Settings, Notepad, Microsoft Word, Calculator, VS Code, and File Explorer
- Web: `Open ChatGPT`, `Open ChatGPT in Chrome`
- System information: battery percentage and available storage
- Discovery: `Help`, `What can you do?`

Common capitalization, punctuation, whitespace, and selected wording variations are normalized.

## Requirements and installation (Windows 11)

Python 3.12 and the existing `.venv` are required. From PowerShell in the project directory:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Run the application:

```powershell
python -m app.main
```

Run tests:

```powershell
python -m pytest
```

Tests mock application launching and system data; they do not open real applications.

## Using microphone commands

Windows must expose at least one enabled input device. Choose a microphone in the selector, use **Refresh microphones** after connecting a device, and use **Test microphone** to validate its input configuration. Click **Microphone**, speak one supported command, and pause. Recording stops after silence or the configured maximum duration. **Stop** ends recording or cancels a pending transcription.

The first use of the default `base.en` faster-whisper model may require a one-time local download. VoxPilot asks before allowing that download; it never requires an API key. Later runs use the cached model. Model, device, compute type, language, beam size, timing, energy threshold, and confidence settings can be changed using the environment variables in `.env.example`.

Microphone audio remains in memory and is zeroed after transcription. Wake audio and command recordings are never written to disk, including when a legacy `VOXPILOT_SAVE_AUDIO=true` setting exists; the development recording-save path has been removed.

## Wake-word mode

Vosk handles **only wake detection**. Enable **Wake-word mode: "Hello"** to stream microphone audio locally in 50 ms frames. A reusable Vosk model and constrained grammar `["hello", "[unk]"]` recognize the default phrase. Only a finalized, exact normalized match activates; partial results, empty/unknown results, `Hello Google`, `Hey Shyam` and other recognized text are ignored. The microphone stream closes and releases the shared lock before activation is emitted.

After activation, Status displays **Wake detected** and Shyam says **“Yes, how can I help you?”**. The UI waits until TTS is idle, applies the existing cooldown, and captures exactly one command. **faster-whisper handles that command transcription**, through the existing router, local planner, validators, confirmations and allowlists. Vosk resumes afterward; wake-listener messages affect Status and the setup notice only, preserving the completed result or PDF summary. Whisper is never invoked to wait for the wake phrase.

Manual microphone and typed commands stop wake listening before proceeding. Stop cancels listening, pending transcription, native decoding, command execution and TTS waiting/speech. It disables wake mode. Closing the application waits for audio workers and terminates the persistent decoder. Temporary disconnections refresh the existing device selection and retry without creating duplicate listeners. Microphone names/host APIs are persisted by the existing selection store. Normal/high sensitivity applies a bounded normal/2x PCM gain for Vosk, while the command recorder retains its existing sensitivity behavior. Both paths share the same microphone lock.

### Local Vosk setup

1. Install the updated requirements in your Python 3.12 runtime (`python -m pip install -r requirements.txt`). Wake detection pins **vosk==0.3.45**, which provides a Windows x64 wheel. No environment was modified automatically for this migration.
2. Manually download **vosk-model-small-en-us-0.15** from the [official Vosk models page](https://alphacephei.com/vosk/models) and extract it to `models/vosk-model-small-en-us-0.15` or another local directory. Point at the extracted model folder containing its model data, not the ZIP. Small models support runtime grammar configuration; arbitrary large/static models may not.
3. Configure these values in your process environment or your own local configuration, then restart VoxPilot:

```dotenv
VOXPILOT_WAKE_ENGINE=vosk
VOXPILOT_WAKE_PHRASE=hello
VOSK_MODEL_PATH=models/vosk-model-small-en-us-0.15
VOSK_SAMPLE_RATE=16000
```

Relative model paths are resolved against the project directory. The default phrase is Hello; the grammar always contains only the normalized configured phrase and `[unk]`. Matching normalizes case, whitespace and punctuation. Activation is consumed before command routing, Ollama or history. A missing model/package displays setup instructions beside wake mode and disables automatic retries until re-enabled. No model is downloaded at runtime, and there is no Whisper/online fallback. Vosk receives 16 kHz mono signed 16-bit PCM; native-rate microphones use stateful conversion before inference.

The Vosk model is loaded once in a persistent local decoder process and reused for normal activations and restarts. Each listening session has a fresh recognizer so previous speech cannot activate a new session. Interrupting a stuck/native decode or model load terminates that process; the next session reloads it. Mutable queues and PCM buffers are cleared, recognizers are released between sessions, and no audio is saved. Python/native temporary immutable copies and operating-system paging are not forensic memory-erasure guarantees. See `MILESTONE6_VOICE_FIX_VERIFICATION.md` for tests and manual checks.

### Windows microphone troubleshooting

- In Windows **Settings > Privacy & security > Microphone**, allow desktop applications to access the microphone.
- If no device appears, connect or enable it, press **Refresh microphones**, and check Windows Sound input settings.
- If a device is busy, close other exclusive-mode audio applications and use **Test microphone** again.
- If model loading fails, confirm the one-time download was approved and that the configured model name is valid. CPU systems should keep `WHISPER_COMPUTE_TYPE=int8`; use `float16` only with confirmed compatible CUDA hardware.

## Ollama configuration

Google search is a fixed-endpoint approved tool. `Search Google for EPITA`, `Google EPITA`, `Open Google and search for EPITA`, and `Find EPITA on Google` route deterministically. Other clear wording may use the local planner, which must return `search_google` with exactly `{"query": "EPITA"}` as its arguments. The model cannot provide a domain, URL, scheme or executable.

Queries must contain 1–300 characters and no controls, line breaks, complete URLs or URI schemes. Case, Unicode, spaces and punctuation are preserved as search data and encoded with `urllib.parse.urlencode` into `https://www.google.com/search?q=...`. Shell-like punctuation is only search text. `Open Google` still opens the homepage. Search submits the query to Google through the browser; intent interpretation remains local. No general URL browsing tool is added.

Milestone 4 uses Ollama only when the deterministic router does not recognize a command. The default local model is `llama3.2:3b`. Exact commands continue working when Ollama is stopped. Install Ollama and pull the model once with `ollama pull llama3.2:3b`; model downloads require internet, but intent processing stays local. No model download is initiated by VoxPilot.

Configure `VOXPILOT_INTENT_MODEL` (default `llama3.2:3b`), `VOXPILOT_INTENT_TIMEOUT` (default 8 seconds, maximum 30), and `VOXPILOT_INTENT_MIN_CONFIDENCE` (default 0.85) through the environment. `VOXPILOT_OLLAMA_BASE_URL` must be an HTTP localhost/loopback endpoint. The intent model setting is independent of the legacy primary/fallback model settings. A cold model may need to be warmed in Ollama before a short request can finish.

Try “Could you bring up Spotify please?”, “Launch my browser please”, “How much battery remains?” or “What date are we on?”. Typed and transcribed requests use the same background command worker. Stop cancels a pending local request; it cannot undo an application already launched.

Ollama must return only `intent`, `arguments`, `confidence` and `requires_confirmation`. Strict Pydantic validation rejects unknown intents, extra or missing fields, incorrect types, duplicate JSON keys and invalid arguments. Public intents `get_time`, `get_date` and `open_safe_url` map to existing internal tools `current_time`, `current_date` and `open_url`. The planner checks confidence and target agreement with the user's words, then the executor and registry independently enforce existing allowlists. Folder creation always enters the explicit confirmation workflow. Other model requests marked as needing confirmation remain rejected.

The client disables proxies and redirects and checks local model metadata before submitting user text. Cloud model names and remote-model aliases are rejected. For a fully local Ollama server, start it with `OLLAMA_NO_CLOUD=1` as described in the [Ollama FAQ](https://docs.ollama.com/faq). Schema-constrained generation follows [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs); server-side formatting never replaces local validation.

Natural-language history stores only the validated tool and allowlisted target, or a generic failed-request label. Raw free-form prompts and model responses are not persisted by VoxPilot or logged. Obvious secret-bearing, destructive, shell, installation, security-change and instruction-override requests are rejected before inference. The exact wake phrase “Hello” is consumed without reaching Ollama or history. Conservative checks also reject compound and negative requests; use a single explicit positive request.

## Local files and folders (Milestone 5)

File commands operate only inside approved local folders. Desktop, Documents, Downloads, Pictures, Music and Videos are resolved through Windows Known Folder APIs, including relocated folder names, and then checked against filesystem policy. Use **Approve project folder** while listening is stopped to add a project. Its assigned identifier (for example `project_1`) is saved in the application's `approved-roots.json` settings and can be used in commands.

Examples: `Open my Documents folder`, `Open Downloads`, `Show files in Downloads`, `List folders in Documents`, `Find my resume in Documents`, `Find files named invoice`, and `Show information about resume.pdf`. The last command defaults to Documents; append `in downloads` to choose another root. Rootless file searches search all approved roots. Search matches visible file names, never file contents. It does not open files or execute them. Results are bounded and marked when truncated.

`Create a folder called Internship Applications in Documents` prepares a proposal without writing. Review the exact parent and folder name in the confirmation panel, then select **Confirm** or **Cancel**. You can use the manual Microphone button to say exactly `Confirm` or `Cancel`. The confirmation expires, is invalidated by another command, and is cancelled by Stop. The model cannot disable this requirement. The destination must not already exist. Wake listening pauses while confirmation is pending and resumes after the action, cancellation or expiry; Stop retains its existing behavior of disabling wake mode.

Default limits are five seconds per operation, search depth four, 100 returned entries, and 30 seconds to confirm. Configure `VOXPILOT_FILESYSTEM_TIMEOUT`, `VOXPILOT_FILESYSTEM_MAX_DEPTH`, `VOXPILOT_FILESYSTEM_MAX_RESULTS`, and `VOXPILOT_CONFIRMATION_TIMEOUT` via the environment; hard caps also apply. Enumeration and OS operations run outside the GUI in bounded worker processes. Listings and local paths are displayed but are not saved in normal command history or sent to Ollama. Only the user's command text can reach local intent planning.

Absolute paths, traversal, device/UNC/network paths, removable drives, alternate streams, hidden/system locations, credential locations, `.git`, virtual environments and all symlinks/junctions are rejected. Root and target paths are revalidated before execution. The policy deliberately rejects even internal links and some redirected/OneDrive folders. No delete, rename, move, copy or existing-file modification is supported. Folder creation is the only user-file write operation; approving roots also updates the application's own settings.

## Local PDF summaries (Milestone 6)

Install the updated `requirements.txt` in your chosen Python 3.12 environment to provide `pypdf>=6.18,<7`. PDF summaries use `VOXPILOT_PRIMARY_MODEL` (default `llama3.2:3b`) through the same loopback-only, proxy-free, redirect-free Ollama transport. The server must report a locally installed model before document text is sent. No PDF is uploaded, edited, decrypted or opened in a PDF viewer.

Try `Summarize resume.pdf in Documents`, `Summarize my resume`, `Give me the main points from report.pdf`, or `Summarize thesis.pdf in Downloads`. `Locate report.pdf` displays explicit choices even for a single match. `Show information about report.pdf` continues to use the existing metadata-only file tool. Deterministic routing runs first; only other safe wording may use the local intent planner.

PDF search is limited to Desktop, Documents, Downloads and explicitly approved `document_N` or `project_N` folders. With no root specified it searches these locations only. Queries are safe filenames or name fragments, never full paths or URLs. Exact `.pdf` filenames match case-insensitively; fragments match PDF basenames. Search stops at depth four, 10,000 visited entries or more than 20 matches; narrow the request if a search limit is reached. A depth-limited search cannot discover deeper files.

Multiple matches require a numbered choice. Select a row and click **Summarize selected PDF**, type a number, or use **Microphone** to say `select two`. Choices show only the logical root and safe relative filename. Selection expires after 60 seconds and is cancelled by an unrelated command, Stop or closing the application. File identity and policy are checked again before extraction. No model can supply the private selection token or choose an absolute path.

The UI displays **Locating PDF**, **Extracting PDF**, **Summarizing**, and the final **Completed**, **Failed** or **Cancelled** status. Page/chunk progress appears below the input. Extraction and model calls run outside the UI thread. Wake listening pauses throughout processing and selection, resumes after completion/failure and any TTS cooldown, and does not overwrite the summary. Stop cancels the operation and native TTS; as before, it disables wake mode. Re-enable wake mode when ready. `Cancel PDF summarization` is also recognized; during a running task use the enabled Stop button.

Strict PDF intent arguments are `root`, `query` and optional `summary_style` (`concise`, `detailed`, or `bullet_points`; default `concise`). Unknown fields, roots, styles and unsafe names are rejected. The existing root resolver rejects sensitive folders, traversal, absolute/UNC/device paths and links/junctions. The read-only parser verifies a regular `.pdf` file, `%PDF-` signature, identity, size and page count. Encrypted, malformed, empty and image-only files fail safely. Image-only files report: “This PDF appears to be scanned or image-based. OCR is not available yet.” Embedded files, JavaScript, actions and hyperlinks are never executed or opened.

| Setting | Default |
| --- | --- |
| `VOXPILOT_PDF_MAX_SIZE_MB` | 20 MB |
| `VOXPILOT_PDF_MAX_PAGES` | 100 |
| `VOXPILOT_PDF_MAX_CHARACTERS` | 200,000 |
| `VOXPILOT_PDF_MIN_CHARACTERS` | 20 meaningful extracted characters |
| `VOXPILOT_PDF_PAGE_CHARACTERS` | 20,000 |
| `VOXPILOT_PDF_EXTRACTION_TIMEOUT` | 60 seconds per search/extraction process |
| `VOXPILOT_PDF_SUMMARY_TIMEOUT` | 180 seconds total across all model calls |
| `VOXPILOT_PDF_MAX_CHUNKS` | 20 |
| `VOXPILOT_PDF_CHUNK_CHARACTERS` | 10,000 including page labels |
| `VOXPILOT_PDF_SPOKEN_SUMMARY_MAX_CHARS` | 300 |
| `VOXPILOT_PDF_SELECTION_TIMEOUT` | 60 seconds |
| `VOXPILOT_PDF_MEMORY_MB` | 512 MB parser-process memory cap |

Size/page limits reject the PDF before extraction. Character, per-page and chunk limits stop further content processing and mark the summary as truncated. Pages remain ordered; empty processed pages are counted. Each bounded chunk is summarized independently, followed by exactly one bounded final synthesis. Intermediate summaries are also capped and any truncation is disclosed. A failure at any stage never displays partial work as a completed summary. Parser processes have a Windows Job Object memory cap and are terminated on Stop or timeout; isolation failures reject processing. This also contains the high memory requirements noted in [pypdf's extraction documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).

Text below `VOXPILOT_PDF_MIN_CHARACTERS` (default 20 word characters after normalization, excluding punctuation/whitespace) returns the exact scanned/image-based OCR limitation message, including PDFs with a little extractable text. The minimum must be positive and cannot exceed the maximum extracted characters. Failure codes survive extraction, the process boundary, service and Qt worker. The UI renders an application-owned message for each code; it never displays raw exception text. Insufficient text, malformed/encrypted files, size/page limits, timeouts and memory failures have distinct codes. Unknown failures are reported generically without guessing that the PDF is invalid or a resource limit was reached.

The summarizer receives only a dedicated text-only system prompt and JSON-delimited untrusted document data. It has no tool schema, router, filesystem capabilities, environment or configuration data. Structured tool requests, JSON, markup, code fences and unsafe control characters in responses are rejected. Accepted summaries render as plain text and never return to the command router. An injected instruction cannot trigger a tool. Like other language models, the local model can still produce inaccurate summaries; compare important details with the source document.

Document text and full summaries are never saved to SQLite or application logs. PDF operations currently opt out of history entirely. Logs contain only timing/cancellation metadata. Text stays in memory; references and containers are cleared after processing, and disposable parser/model transport processes exit. Python immutable strings and OS paging cannot provide cryptographic memory erasure. No temporary extracted text is written to disk. Spoken summaries are optional and limited to the short overview; the full text remains visible.

See `MILESTONE6_VERIFICATION.md` for test evidence, manual acceptance steps and limitations. This milestone does not implement OCR, remote PDFs, document writes or recursive/unlimited summarization.

## Known limitations

- Vosk waits for a finalized utterance; a short pause after Hello is required. Acoustic false positives/misses remain possible with noise, accents, or a constrained recognizer. Exact matching applies to recognized text, not ground-truth speech.
- The Stop button reports status but cannot terminate an already launched OS application.
- Application availability depends on standard Windows registrations and executable names.
- `Open ChatGPT in Chrome` currently opens the approved URL through the system browser rather than forcing a particular browser.
- Speech confidence is language-level because faster-whisper does not expose a single universal utterance confidence value.
- Native Whisper runs in a persistent process for command transcription only. Vosk uses a separate persistent wake decoder. Stop or timeout can terminate an in-flight native process; its model loads again on the next request. Native TTS is also isolated so a timeout cannot leave audible speech running while capture resumes.
- Native-rate conversion uses Python 3.12's stateful `audioop.ratecv`; it must be replaced before supporting Python 3.13, where audioop is removed. This project continues to require Python 3.12.

## Roadmap

Future milestones may add a dedicated custom wake model and additional carefully designed approval flows. Destructive actions remain unimplemented.

## Milestone 7: approved project management

Use **Approve projects folder**, then **Refresh projects**. Only explicitly approved `project_N` roots are scanned; Desktop, Documents, the current working directory and drive roots are not implicitly project roots. Existing filesystem containment, Unicode name validation, symlink/junction and sensitive-directory restrictions still apply. Discovery reads manifest names and metadata, not source contents. It skips virtual environments, dependency trees, build output and hidden folders.

Supported commands include:

- `List my projects` / `List projects in project_1`
- `Open the CyberGuard project` / `Open project VoxPilot`
- `Show project information for CyberGuard`
- `Start the CyberGuard project` / `Run project VoxPilot`
- `Show running projects`
- `Stop the CyberGuard project`

Deterministic routing runs first. Ollama can return only a tool name and literal project name (or a logical root for listing). It cannot supply executable paths, arguments, PIDs, environment variables or profiles. Ambiguous names produce numbered choices. Opening means opening the validated folder in Explorer; it does not run code.

### Explicit launch profiles

Pause wake mode, choose **Save launch profile**, and paste one JSON object. Validation runs in a worker before saving. Profiles are stored in `project-profiles.json` in the application's local data directory, alongside the existing approved-root configuration. Saving a profile does not start it. Use a stable unique `project_id`; saving the same identifier replaces that profile after validation. Start with one profile per discovered project directory. Refresh the project list after saving.

These examples use generic installation locations; replace them with an existing local executable and the correct approved root/relative directory. No executable is searched on PATH or downloaded automatically.

Python module (equivalent to the fixed `python -m app.main` launch):

```json
{
  "project_id": "voxpilot",
  "display_name": "VoxPilot",
  "root": "project_1",
  "directory": "VoxPilot",
  "runner": "python_module",
  "executable": "C:/Python312/python.exe",
  "entry_point": "app.main",
  "arguments": [],
  "working_directory": "",
  "environment_allowlist": ["SYSTEMROOT", "WINDIR", "TEMP", "TMP"],
  "allow_duplicate": false
}
```

For `python_script`, use a contained relative `.py` entry point such as `main.py`. A project-local `.venv/Scripts/python.exe` may be selected explicitly as the executable after link/reparse validation; this narrow executable rule does not allow discovery or file tools to browse virtual environments. Module entry points must exist in the project, and module launches use its root as the working directory. Fixed arguments are bounded simple values, without paths, traversal, control characters or shell syntax. No pip installation or environment activation runs.

Fixed npm script:

```json
{
  "project_id": "dashboard",
  "display_name": "Dashboard",
  "root": "project_1",
  "directory": "Dashboard",
  "runner": "npm_script",
  "executable": "C:/Program Files/nodejs/node.exe",
  "npm_cli": "C:/Program Files/nodejs/node_modules/npm/bin/npm-cli.js",
  "entry_point": "dev",
  "arguments": [],
  "environment_allowlist": ["SYSTEMROOT", "WINDIR", "TEMP", "TMP"]
}
```

`dev` must already be a script in `package.json`. Windows `npm.cmd` is not launched: validated `node.exe` runs the explicitly configured npm CLI belonging to that Node installation. The fixed invocation uses `--ignore-scripts run-script dev`, disabling automatic pre/post lifecycle hooks. It never adds npm options or installs dependencies. The selected manifest script is trusted project code and may itself have side effects; review it before approving the profile.

Fixed Docker Compose file:

```json
{
  "project_id": "localweb",
  "display_name": "Local Web",
  "root": "project_1",
  "directory": "LocalWeb",
  "runner": "docker_compose",
  "executable": "C:/Program Files/Docker/Docker/resources/bin/docker.exe",
  "entry_point": "compose.yaml",
  "arguments": [],
  "environment_allowlist": ["SYSTEMROOT", "WINDIR", "TEMP", "TMP"]
}
```

The Compose file currently requires **JSON syntax (a YAML subset)**. Its only top-level field is `services`; each named service allows only a digest-pinned `image`, optional Boolean `init`, and optional Boolean `read_only`. Use an actual locally available image digest, for example:

```json
{"services":{"web":{"image":"nginx@sha256:REPLACE_WITH_64_HEXADECIMAL_DIGEST_CHARACTERS","read_only":true}}}
```

The placeholder deliberately fails validation until replaced. Other Compose features—including builds, commands, environment files, ports, volumes, host mounts, privileged mode, devices, includes and extensions—are rejected. Docker uses only the fixed local Windows named-pipe endpoint, no builds/pulls, an empty environment file and an internal unique project name. The reviewed manifest snapshot is supplied in memory to both start and stop, so stop does not reread a changed Compose file. See the official [Compose up options](https://docs.docker.com/reference/cli/docker/compose/up/).

### Confirmation and process lifetime

Every start and stop displays its exact plan and requires **Yes/Confirm** or **No/Cancel**. The token expires after 30 seconds by default, is single-use and is bound to a SHA-256 hash of the plan. Profiles, paths, file identities and entry/manifest hashes are checked again on confirmation. Modified, expired or replayed plans cannot launch. Wake listening stays paused during confirmation, and confirmation replies do not enter command routing or history.

All launches use argument arrays with `shell=False`. Only profile-approved executables are allowed; no raw command-string API exists. This is an approval boundary, **not an OS sandbox for project source code**. Approve only projects, interpreters, npm scripts and images you trust: launched code retains your normal Windows permissions. Source dependencies are not recursively hashed or audited, and concurrent modification by another local process cannot be fully prevented.

Each process has an internal instance identifier, project identifier, PID, start time, runner and state. A private supervisor assigns the new process to a Windows Job Object while suspended, before its first instruction; descendants remain in that owned job. No existing process or user-supplied PID is attached. See [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects). Duplicate starts are blocked unless the saved profile explicitly allows them. Stop requires a separate confirmation, attempts graceful termination, then forces only the owned job after the configured timeout. Docker first receives a fixed stop for its unique Compose project; daemon failures produce an unverified/failure state rather than a successful-stop claim.

The red Stop button cancels VoxPilot work and pending confirmations. It does not implicitly terminate launched projects. Closing VoxPilot leaves projects running: detached supervisors continue draining and discarding output until their owned trees exit. No project-management worker threads remain in the UI. Tracking is session-only; a restarted UI deliberately cannot attach to or kill projects from a previous session. Use their normal application/Docker controls after exiting VoxPilot.

Use **Refresh process output** to update the separate read-only output panel and states. Output is kept only in bounded memory, decoded with replacement, redacted for sensitive assignments, and discarded after retention or detachment. Partial lines are withheld until complete or bounded. Project requests, plans and output are not saved in command history. Only explicitly allowed non-sensitive environment names are inherited: `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, `LANG`, `LC_ALL`, `PYTHONUTF8`. Names containing TOKEN, KEY, SECRET, PASSWORD, CREDENTIAL or AUTH are prohibited, as are PATH and Python/Node startup injection variables. Redaction is best-effort for arbitrary project output; avoid printing secrets.

### Limits and verification

Defaults in `.env.example`: discovery depth 3, 1,000 directories/entries per directory, 100 results and 15 seconds; output 500 lines/262,144 bytes per project; confirmation 30 seconds; graceful stop 10 seconds; completed output retention 60 seconds. The session tracks at most 100 instances. Manifest/profile/entry reads are limited to 64 KiB. Bounded scans may omit deeper or very wide projects; increase limits deliberately within validated caps. Rust and Go are discoverable/openable but have no inferred launch runner.

See [MILESTONE7_VERIFICATION.md](MILESTONE7_VERIFICATION.md) for test results, limitations and manual acceptance steps. Existing wake detection, Whisper commands, URL allowlists, filesystem and PDF policies remain authoritative.

## Milestone 8: Local Knowledge

Local Knowledge indexes text-based PDF, UTF-8 TXT and Markdown files, retrieves relevant excerpts, and answers questions with file/page citations. Source files are read only. Word, PowerPoint, OCR, images, websites and remote documents are not supported.

### Setup and first use

Install the embedding model yourself in the local Ollama installation:

```powershell
ollama pull nomic-embed-text
```

The answer model uses `VOXPILOT_PRIMARY_MODEL` (default `llama3.2:3b`) and must also already be installed. VoxPilot never downloads models automatically. Both requests use the configured HTTP loopback Ollama endpoint; redirects, environment proxies, remote model metadata and cloud model names are rejected. Embeddings use Ollama's documented [`/api/embed` endpoint](https://docs.ollama.com/api/embed) with truncation disabled. One transient connection/timeout retry is allowed within the operation deadline; there is no online fallback.

Select **Load index / sources** in **Local Knowledge** to load approved source identifiers and the document count. Select one source, then **Index documents**. Desktop, Documents and Downloads use the existing Windows Known Folder policy. To use a different folder, stop wake listening and use **Approved Locations → Add approved folder** with **General document location** selected. Its saved `document_N` identifier appears in the source selector. Existing `project_N` sources remain supported. Folder approval is shared with the filesystem, PDF, Knowledge and project services; only project approvals enable project discovery.

Examples:

- `Index PDFs in Documents` — PDF only in that selected root.
- `Index documents in project_1` — PDF, TXT and Markdown in that selected root.
- `Refresh my document index` — rescan previously indexed scopes.
- `Show indexed documents` — safe relative names, status and PDF page counts.
- `Ask my documents: What are the main risks?`
- `Search my documents for data governance`
- `Which document discusses cloud security?`
- `Show sources for the last answer`
- `Remove report.pdf from the index`
- `Clear the document index`

Root selection is required for indexing; an unspecified or `all` root is rejected. Duplicate filenames produce up to 20 numbered choices before a removal proposal. Removal and clearing require a separate **Yes/Confirm**; **No/Cancel**, expiry, another command, Stop and closing invalidate proposals. Tokens expire after 30 seconds, are single-use and bind the action and current index revision. Clearing removes local index entries only, never source files. Removed files can be indexed again by a later refresh of their source scope.

### Evidence and privacy

Answers appear in a dedicated panel with plain source labels and bounded excerpts. PDF citations include page numbers. Select a source and use **Open selected approved source** to open it through the guarded Windows filesystem adapter; the source is revalidated against its approved root, identity and content hash first. There are no executable citation links. TXT/Markdown have no synthetic page numbers.

Questions retrieve at most six chunks by default, with a minimum cosine similarity of 0.25 and at most two chunks per document. Overlapping chunks and duplicate excerpt text are suppressed. Weak evidence produces an insufficient-information message. Answer JSON is strictly validated and each citation must exactly match a retrieved chunk. Invalid model output or model failure displays retrieved excerpts instead of an answer. Citation validation proves which supplied chunk is referenced; it cannot prove the truth of every generated sentence. Review the excerpts for consequential uses.

Document content is untrusted data. It cannot execute tools, change policy or become another VoxPilot command. Answer generation has no tools and uses separate system instructions, question and evidence fields. Only bounded retrieved content goes to the local answer model, never arbitrary file access or unrestricted absolute source paths. Keep Ollama configured for local-only operation as described above.

The versioned index is `knowledge-v1.sqlite3` in VoxPilot's application-data directory, outside source folders. SQLite stores metadata, chunk text, and checksummed little-endian float32 vectors together. NumPy performs bounded cosine retrieval; there is no network vector database or pickle. SQLite transactions commit the whole indexing operation or roll it back. Unknown schema versions and corrupt rows fail closed without automatic migration. Index files are ignored by Git. The index contains readable document excerpts and is protected by the current Windows account's filesystem permissions, not application-level encryption. Questions, answers and excerpts are excluded from command history and logs.

Unchanged content hashes reuse embeddings. Renames preserve document identity when the filesystem identity and content match; copied files have separate identities, with duplicate excerpts suppressed during retrieval. Changed documents replace their old chunks; successful refresh removes deleted or revoked sources. Before retrieval and again after generation, source identity, hash and approval are rechecked. Stale or inaccessible sources cannot provide answers even before a refresh.

### Limits and cancellation

`.env.example` documents all required knowledge settings. Defaults: 1,800 characters per chunk, overlap 250, 500 documents, 500 chunks per document, 50,000 total chunks, 20 MiB per file, 600 seconds per indexing operation, 120 seconds per query, and 6,000 answer characters. Additional hard limits include 4,096 vector dimensions, 512 MiB for the SQLite main file, 10,000 discovery entries, depth four, 24,000 retrieved context characters, and 20 ambiguous removal choices. SQLite's rollback journal can temporarily require roughly another database's worth of disk space. Invalid configurations are rejected.

Existing PDF limits apply, including page, character, parser memory and extraction-time bounds. Scanned PDFs report that OCR is unavailable; encrypted, malformed and truncated PDFs are rejected. TXT/Markdown use bounded UTF-8 replacement decoding; binary NUL-containing files are rejected. Hidden/system files, links/junctions, environment files, keys, credential locations, dependency trees, build output, logs and database formats are excluded. A discovery, extraction, embedding or storage failure aborts the update; an old committed index remains intact. Approve a smaller dedicated source folder if its depth, width or content exceeds limits.

All knowledge operations run through retained Qt command workers; parsing, hashing, discovery and HTTP requests use cancellable isolated processes. **Cancel** in Local Knowledge rolls back work and allows enabled wake mode to resume. The existing red **Stop** also cancels knowledge work and retains its established behavior of disabling wake mode. Closing cancels active workers before exiting. Short spoken notifications refer to the visible answer and sources; the full answer is not read aloud. Wake resumption does not erase the answer.

Chunk text intentionally persists in the local index. Extraction and request buffers are released after use; mutable raw byte/vector buffers are cleared. Python immutable strings, SQLite/OS caches, paging and storage devices cannot promise forensic erasure. Revalidations narrow filesystem races but cannot defeat a hostile process running with the same account privileges. See [MILESTONE8_VERIFICATION.md](MILESTONE8_VERIFICATION.md) for tests, limitations and manual acceptance steps.

## Approved Locations

Stop listening before managing folder approvals. The **Approved Locations** section shows each identifier, folder name, full path, availability and approval type. Use:

- **Add approved folder**: choose General document location or Projects location, then select a local fixed-drive folder. Multiple folders and explicitly approved nested folders are supported.
- **Remove selected folder**: confirm the identifier and full path. Only approval is removed; the folder and its files remain intact. Other approvals for a parent or child remain effective.
- **Open selected folder**: revalidate the approval and open the folder through the Windows adapter.
- **Refresh folders**: reload availability and update the Local Knowledge source selector.

Examples: `Open document_1`, `Show files in document_1`, `Find files named invoice in document_1`, `Summarize report.pdf in document_1`, and `Index documents in document_1` (use your displayed identifier).

Approvals are saved with atomic replacement in the application's `approved-roots.json`. Existing project approvals migrate on the next change. Removed identifiers are reserved so existing index records and launch profiles cannot silently refer to a different folder. Removing a built-in Known Folder persists across restarts. Invalid/unreadable settings fail closed and show an error; missing folders remain listed for removal or troubleshooting.

All descendants are within an approved root's scope, subject to existing sensitive-name, hidden/system, reparse-point and resource-limit rules. Recursive discovery retains its depth/time/result limits; explicitly approve a narrower nested folder when necessary. Drive roots, the user profile, the application repository and its ancestors, sensitive system paths, UNC/network/device paths, traversal and symlink/junction escapes are blocked. Every operation resolves and checks its root and target again. As before, path checks are not an OS sandbox against concurrent changes by another local process.

Pictures, Music and Videos retain their existing general filesystem access; approve them explicitly as document locations to use them for PDF/Knowledge processing. General document approval does not grant project launch approval. Existing project launch confirmations and executable allowlists still apply.

See `APPROVED_LOCATIONS_VERIFICATION.md` for verification results.
