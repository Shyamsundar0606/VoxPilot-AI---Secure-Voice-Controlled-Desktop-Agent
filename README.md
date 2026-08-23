# VoxPilot AI

VoxPilot AI is a local-first Windows desktop assistant. Its voice identity is **Shyam**. The project aims to make common laptop actions accessible through natural language while keeping execution deterministic, restricted, and private.

Milestone 1 establishes the safe desktop foundation. It provides typed commands and local spoken responses; real microphone recognition and wake-word detection are deliberately deferred.

## The problem

General-purpose automation can turn generated text into unsafe operating-system commands. VoxPilot instead routes recognized phrases to a small allowlist of reviewed tools and fixed application identifiers. Unknown requests are rejected rather than guessed.

## Milestone 1 features

- Dark PySide6 desktop interface titled **VoxPilot AI**, with **Shyam** as the assistant
- Typed command input, Execute, microphone placeholder, and Stop controls
- Idle, Listening, Processing, Completed, and Failed status model
- Command, result, and SQLite-backed history panels
- Background command execution and background `pyttsx3` speech
- Spoken-response toggle and graceful error handling
- Deterministic command router; Ollama is optional and never required for supported commands
- Mockable Windows tool layer for time, date, battery, storage, approved applications, approved URLs, and help

## Architecture

`app/ui` contains presentation and worker threads. `app/agent` routes and executes requests. `app/tools` contains the only approved side effects. `app/security` validates tool names and arguments. `app/database` persists history. `app/voice` isolates text-to-speech. Typed Pydantic models carry requests and results between layers.

## Technology

Python 3.12, PySide6, Pydantic, psutil, pyttsx3, requests, platformdirs, SQLite, and pytest. No paid service, API key, Docker, or administrator access is required.

## Security design

- Tools and applications are allowlisted; application launch data comes only from fixed source mappings.
- Arbitrary paths, shell commands, PowerShell, `eval`, and `exec` are never accepted.
- Unsupported, sensitive, and destructive commands fail safely.
- URLs are selected by approved symbolic names.
- Ollama JSON is schema-validated and policy-validated before it can become a tool request.
- History stores command outcomes but no credentials or secrets.

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

## Ollama configuration

Ollama is an optional adapter for future interpretation of otherwise unknown requests. Defaults are `http://localhost:11434`, primary model `qwen3:latest`, and fallback `llama3.2:3b`. Configuration can be overridden with the variables shown in `.env.example`. Known deterministic commands do not call Ollama, and no model is permitted to execute commands directly.

## Known limitations

- The microphone button is informational; there is no speech recognition or wake word yet.
- The Stop button reports status but cannot terminate an already launched OS application.
- Application availability depends on standard Windows registrations and executable names.
- `Open ChatGPT in Chrome` currently opens the approved URL through the system browser rather than forcing a particular browser.
- Background tasks use a safe fixed tool set; there is no general automation engine.

## Roadmap

Milestone 2 is planned to add microphone transcription and wake-word behavior. Later milestones may add carefully approved tools and confirmation flows for sensitive actions. Those features are not implemented today.

