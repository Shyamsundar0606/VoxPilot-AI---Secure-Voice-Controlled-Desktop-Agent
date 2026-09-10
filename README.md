# VoxPilot AI

VoxPilot AI is a local-first Windows desktop assistant. Its voice identity is **Shyam**. The project aims to make common laptop actions accessible through natural language while keeping execution deterministic, restricted, and private.

Milestone 1 established the safe desktop foundation. Milestone 2 adds local, click-to-record microphone commands. Wake-word detection remains deliberately deferred.

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

## Architecture

`app/ui` contains presentation and retained Qt workers. `app/agent` routes and executes requests. `app/tools` contains the only approved side effects. `app/security` validates tool names and arguments. `app/database` persists history. `app/voice` separates device discovery, in-memory recording, local transcription, routing coordination, and text-to-speech. Typed Pydantic models carry requests and results between layers.

## Technology

Python 3.12, PySide6, Pydantic, psutil, pyttsx3, faster-whisper, sounddevice, NumPy, requests, platformdirs, SQLite, and pytest. No paid service, API key, Docker, or administrator access is required.

## Security design

- Tools and applications are allowlisted; application launch data comes only from fixed source mappings.
- Arbitrary paths, shell commands, PowerShell, `eval`, and `exec` are never accepted.
- Unsupported, sensitive, and destructive commands fail safely.
- URLs are selected by approved symbolic names.
- Ollama JSON is schema-validated and policy-validated before it can become a tool request.
- History stores command outcomes but no credentials or secrets.
- Audio is processed locally in memory and is not uploaded or saved by default.
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

Microphone audio remains in memory and is zeroed after transcription. Development audio saving exists only through the explicit `VOXPILOT_SAVE_AUDIO=true` opt-in and is disabled by default.

## Wake-word mode

Enable **Wake-word mode: "Hello"** to listen locally for the wake phrase. VoxPilot uses short, energy-gated audio windows and invokes the shared faster-whisper model only when speech is detected; it does not run Whisper on every audio frame. After hearing the phrase, Shyam replies **“Yes, how can I help you?”**, waits through a self-trigger cooldown, records one command, sends that text through the existing deterministic allowlist, and then resumes wake listening.

Manual microphone and typed commands remain available. Starting either pauses the wake listener first. Stop disables and cancels wake mode. Continuous audio stays in memory and is never saved. On CPU, this fallback is more resource-intensive and slower than a purpose-built wake engine, but it requires no cloud service or custom wake model.

The fixed wake phrase is configured by `WAKE_PHRASE = "Hello"` in `app/config.py`. Matching requires the entire normalized transcription: `Hello`, `hello`, `HELLO!` and `Hello.` activate it, including surrounding whitespace. `Hey Shyam`, `Hello Google` and `Open Chrome` do not activate it. The wake utterance is consumed before command routing and never enters command history. The acknowledgement remains “Yes, how can I help you?”

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

## Known limitations

- Wake detection uses short-window Whisper fallback rather than a dedicated custom "Hello" model, so latency depends on CPU performance.
- The Stop button reports status but cannot terminate an already launched OS application.
- Application availability depends on standard Windows registrations and executable names.
- `Open ChatGPT in Chrome` currently opens the approved URL through the system browser rather than forcing a particular browser.
- Speech confidence is language-level because faster-whisper does not expose a single universal utterance confidence value.
- Native Whisper runs in one persistent local worker process shared by wake and command transcription. Stop or timeout terminates that process; the model loads again on the next request. Normal speech windows reuse the loaded model. Native TTS is also isolated so a timeout cannot leave audible speech running while capture resumes.

## Roadmap

Future milestones may add a dedicated custom wake model and additional carefully designed approval flows. Destructive actions remain unimplemented.
