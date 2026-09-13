# VoxPilot AI

VoxPilot AI is a local-first Windows desktop assistant. Its voice identity is **Shyam**. The project aims to make common laptop actions accessible through natural language while keeping execution deterministic, restricted, and private.

Milestones 1–6 provide safe desktop tools, local speech recognition, exact "Hello" wake activation, local intent planning, approved-folder operations and local PDF summarization.

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

PDF search is limited to Desktop, Documents, Downloads and approved `project_N` folders. With no root specified it searches these locations only. Queries are safe filenames or name fragments, never full paths or URLs. Exact `.pdf` filenames match case-insensitively; fragments match PDF basenames. Search stops at depth four, 10,000 visited entries or more than 20 matches; narrow the request if a search limit is reached. A depth-limited search cannot discover deeper files.

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
