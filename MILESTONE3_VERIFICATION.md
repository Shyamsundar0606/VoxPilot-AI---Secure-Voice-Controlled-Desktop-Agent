# Milestone 3 implementation and verification

## Qt routing investigation and fix

The inspected checkout did not contain a wake-transcription connection to the normal command slot: the original path was `WakeWordController.listen_once` → `WakeWordWorker.detected` → `MainWindow._wake_detected` → `_wake_finished` → TTS/cooldown → a new recording. Consequently, the reported `Failed: Hello` history entry could not be reproduced or attributed conclusively to a misconnection in this source. A confirmed boundary weakness was that `TranscriptionWorker.finished` connected directly to the untyped `_store_voice_result`, without worker identity or transcription-source validation.

That connection is replaced by `TranscriptionWorker.result_ready(result, source)` → `VoiceSignalRelay.transcription` → `_store_transcription_result`. The source is explicitly `manual` or `wake_command`, assigned when capture starts. Wake windows instead use `WakeWordWorker.activation(text)` → `VoiceSignalRelay.activation` → `_wake_activation`; this path normalizes and consumes the activation without routing or history access. It does not use the checkbox to classify the text source.

Each GUI-thread relay retains its worker's session identity and only forwards events from the current worker. This also avoids relying on `QObject.sender()` after a worker has been deleted before queued delivery. Relays hold a weak window reference to avoid an ownership cycle, and are deleted at thread completion. Workers retain their existing `deleteLater` teardown. Restarts wait until the old wake thread finishes, use fresh cancellation events, and reject stale results, errors, states and completion events. Duplicate activation is ignored once acknowledgement is pending.

New signal-level integration tests emit `Hello`, duplicate and stale activation, and the second `Open Google` transcription through the production connections. They check no activation routing, history or unsupported handling; unchanged acknowledgement; one command capture; explicit manual routing; and repeated toggling with one active wake worker. Existing real-QThread event-loop tests also pass.

Verification for this fix: requested four-file focused suite **65 passed**; new signal integration file **3 passed**; complete suite **178 passed**. Earlier development iterations exposed test failures and a relay ownership-cycle crash, which were corrected before these successful final runs. Manual reproduction of the originally reported running application remains unverified.

Changed for this fix: `app/ui/workers.py`, `app/ui/main_window.py`, new `tests/test_ui_voice_signals.py`, and this report. `.env`, `.venv` and `venv` were not modified; no commit was created.

## Wake phrase update — 2026-09-09

The fixed phrase is now `Hello`, defined once in `app/config.py` and shared by matching and the UI label. Matching requires the whole normalized transcription; capitalization, surrounding whitespace and punctuation are normalized. `Hey Shyam` and `Hello Google` no longer activate listening. The acknowledgement remains `Yes, how can I help you?`. Activation is consumed without reaching the router, executor or history; the Qt integration test uses a real wake controller with mocked `HELLO!` transcription before capturing exactly one subsequent command.

Files changed for this update: `app/config.py`, `app/voice/wake_word.py`, `app/ui/main_window.py`, `tests/test_config.py`, `tests/test_wake_word.py`, `tests/test_runtime.py`, `tests/test_transcriber.py`, `README.md`, and `MILESTONE3_VERIFICATION.md`. Shared Whisper processing, microphone locking, TTS cooldown and command security controls were preserved. No `.env`, `.venv` or `venv` edits and no commit were made.

Current automated results: focused suite **82 passed**, complete suite **175 passed**, using Python 3.12.10. Real microphone acceptance remains a manual check; the application-launch note below records the earlier milestone verification, not a new launch for this update.

The existing uncommitted milestone work was preserved and extended. Automated verification is complete; real microphone recognition, audible TTS, browser launch and physical-device disconnect checks require the manual steps below. Do not interpret mocked tests or successful startup as proof of those hardware checks.

## Files

New relative to Git: `app/voice/wake_word.py`, `tests/test_wake_word.py`, `tests/test_web_tools.py`, and this report. The first two already existed as untracked user work when this task began.

Modified during this task: `app/config.py`, `app/main.py`, `app/agent/router.py`, `app/tools/web_tools.py`, `app/ui/main_window.py`, `app/voice/recorder.py`, `app/voice/transcriber.py`, `app/voice/tts.py`, `requirements.txt`, `README.md`, `tests/test_router.py`, `tests/test_runtime.py`, `tests/test_transcriber.py`, `tests/test_tts.py`, and the two pre-existing untracked wake files.

Other existing user modifications were preserved: `.env.example`, `AGENTS.md`, `app/models.py`, `app/security/policy.py`, `app/ui/workers.py`, `app/voice/audio_devices.py`, `tests/test_audio_devices.py`, and `tests/test_config.py`.

## Architecture and safety

- `WakeWordController` consumes normalized wake text as an activation event. The Qt wake worker only signals detection; it has no router, executor or history access. The UI waits for that worker to finish before starting one subsequent command recording.
- The existing recorder supplies energy gating, sensitivity, bounded windows and in-memory audio. Wake settings force audio saving off. Recorder frames, queued buffers and transcription inputs are cleared on normal completion and failure/cancellation paths.
- A recorder-wide nonblocking lock excludes simultaneous microphone recording/testing across recorder instances. UI orchestration also cancels and waits for wake listening before typed or manual command handling.
- Qt signals carry worker updates. Generation guards invalidate delayed TTS/cooldown callbacks after Stop, mode changes or close. Result TTS and acknowledgement TTS finish before listening resumes; enabled speech uses the configurable 1.5-second cooldown.
- One shared `SpeechTranscriber` lazily owns one persistent native Whisper process. Wake and command paths reuse its model. An inference lock prevents overlapping calls. Timeout or cancellation terminates the native process; subsequent use reloads it. Application close shuts down the model and TTS resources.
- Native pyttsx3 runs in a bounded child process, allowing a timeout to terminate audible speech before releasing the busy state. No cloud speech service, API key or raw-audio file is involved.
- Project-root `.env` loading uses `python-dotenv` before settings creation with `override=False`. `auto` resolves to CPU; normal defaults are int8 and beam size 1. Explicit CUDA settings remain supported.
- Google aliases route only to the existing fixed HTTPS URL allowlist. The result is `Google is now open.` Chrome remains a separate application command. Dangerous commands and arbitrary executable paths remain unsupported.

## Verification

Python on PATH was unavailable. Verification used the existing `.venv/Scripts/python.exe`, Python 3.12.10, without installing into or modifying the virtual environment.

Focused command: `.\.venv\Scripts\python.exe -m pytest tests/test_wake_word.py tests/test_runtime.py tests/test_transcriber.py tests/test_config.py tests/test_tts.py tests/test_audio_devices.py -v` — **82 passed**.

Full command: `.\.venv\Scripts\python.exe -m pytest -v` — **175 passed**. `git diff --check` succeeded; Git only emitted line-ending conversion warnings. The staging area is empty: `.env`, virtual environments, recordings, databases, logs and model files are not staged. Tests use mocked audio, model, application and browser boundaries. Qt integration covers one-command capture, safe rejection, resumed listening and Stop cleanup. Native process lifecycle tests mock the process boundary rather than loading Whisper or speaking aloud.

Application launched using `.\.venv\Scripts\python.exe -m app.main`; no startup error was emitted. This does not verify real model loading or the microphone interaction.

## Exact manual acceptance steps

1. Restart the app with `.\.venv\Scripts\python.exe -m app.main` to load the latest code. Select the intended microphone, refresh devices and test it while listening is stopped.
2. Enable spoken responses and `Wake-word mode: "Hello"`. Confirm `Wake-word listening`.
3. Say `Hey Shyam`, `Hello Google`, and `Open Chrome` separately. Confirm no activation, desktop action or command-history entry.
4. Say `Hello`. Confirm `Wake detected`, then hear `Yes, how can I help you?`. Wait for the acknowledgement and 1.5-second cooldown to finish and `Command listening` to appear.
5. Say `Open Google`. Confirm Google opens once, `Google is now open.` appears, only the command enters history, and wake listening resumes after result speech. Repeat with `Go to Google`, `Launch Google`, and `Open Google website`.
6. Activate again, then say `Delete my files`. Confirm rejection, no filesystem action and resumed wake listening.
7. Repeat activation with spoken responses disabled. Confirm command capture starts without acknowledgement audio.
8. Press Stop during wake listening, acknowledgement/cooldown, recording and transcription in separate runs. Confirm the checkbox is cleared and no delayed callback restarts capture.
9. While wake mode is active, test the manual Microphone flow and a typed time command. Confirm no overlapping microphone stream. Test Chrome, Spotify, Settings and current time normally.
10. Toggle wake mode repeatedly. Disconnect the microphone during listening, reconnect, refresh/reselect and retry. Confirm responsive UI and no duplicate listener.
11. Close during listening and during transcription. Confirm the application and its native speech children exit. Restart and verify the saved wake preference is restored after initialization.

## Limitations

- No real spoken acceptance result has been supplied yet; hardware acceptance remains pending.
- Whisper fallback latency and recognition of the name depend on local hardware, pronunciation and noise. Language probability is a coarse confidence filter.
- A native timeout/cancellation intentionally discards the loaded process, so the next speech request has model-loading latency.
- An already launched allowlisted desktop application cannot be undone by Stop.
- No commit was created. The private `.env` and virtual environments were not edited, and no recordings were saved by this task.
