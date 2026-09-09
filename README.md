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

Ollama is an optional adapter for future interpretation of otherwise unknown requests. Defaults are `http://localhost:11434`, primary model `qwen3:latest`, and fallback `llama3.2:3b`. Configuration can be overridden with the variables shown in `.env.example`. Known deterministic commands do not call Ollama, and no model is permitted to execute commands directly.

## Known limitations

- Wake detection uses short-window Whisper fallback rather than a dedicated custom "Hello" model, so latency depends on CPU performance.
- The Stop button reports status but cannot terminate an already launched OS application.
- Application availability depends on standard Windows registrations and executable names.
- `Open ChatGPT in Chrome` currently opens the approved URL through the system browser rather than forcing a particular browser.
- Speech confidence is language-level because faster-whisper does not expose a single universal utterance confidence value.
- Native Whisper runs in one persistent local worker process shared by wake and command transcription. Stop or timeout terminates that process; the model loads again on the next request. Normal speech windows reuse the loaded model. Native TTS is also isolated so a timeout cannot leave audible speech running while capture resumes.

## Roadmap

Future milestones may add a dedicated custom wake model and carefully designed confirmation flows. Destructive actions remain unimplemented.
