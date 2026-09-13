# Milestone 6 voice fix — local streaming Vosk wake detection

Verified on Windows with Python 3.12, 2026-09-13. No files were staged or committed. Private `.env`, `.venv` and `venv` were not modified.

## Architecture

Vosk now handles continuous wake detection only. `app/voice/wake_word.py` no longer records Whisper windows or calls a transcriber. `app/main.py` creates one Vosk controller separately from the existing command-only faster-whisper transcriber.

The controller opens one selected microphone stream with 50 ms frames, mono signed 16-bit PCM. A bounded queue holds at most 20 frames. Devices requiring 44.1/48 kHz or another supported native rate use stateful conversion before inference; Vosk always receives 16 kHz mono signed 16-bit PCM. Silence is passed to the recognizer so it can finalize utterances. Normal/high sensitivity reuses the UI setting with normal/bounded 2x gain. Command recording keeps its existing sensitivity behavior.

One persistent local decoder process loads the Vosk model from the explicit configured directory. The default grammar is exactly `["hello", "[unk]"]`. Each listening session creates a fresh recognizer using that model; normal activation/resumption reuses the model. Only `AcceptWaveform`-finalized `Result().text` is considered. Partial results and forced finalization on closing are never used. Normalization covers case, whitespace and punctuation, then compares the whole recognized text. Empty results, `[unk]`, Hello Google, Hey Shyam and unrelated final results do not activate.

On an exact match, the stream closes, temporary buffers are cleared, the recognizer is reset and the microphone lock is released **before** WakeWordWorker emits activation. The UI displays Wake detected, speaks “Yes, how can I help you?”, waits for TTS idle/cooldown and starts exactly one command capture. faster-whisper transcribes that command. Routing, local intent planning, validators, confirmations and approved tools remain authoritative. The wake phrase never enters the command router, Ollama or history.

After command success or failure, enabled wake mode resumes Vosk listening. It updates Status and the dedicated wake setup/recovery notice, preserving the completed execution result and PDF summary. Pending filesystem confirmations and PDF selections continue to pause listening.

## Lifecycle and privacy

- Vosk and the command recorder use the same `AudioRecorder._microphone_lock`; a controller session lock also rejects duplicate sessions. The UI retains only one wake worker and waits for its teardown before manual microphone capture.
- Existing worker-identity relays ignore stale results. Workers recheck cancellation before emitting activation. Disabling/re-enabling wake mode cancels an already-pending old activation.
- Stop cancels the stream loop, command recording/transcription, TTS waiting/speech and active command execution. Closing waits for audio workers and releases the persistent decoder process.
- Model startup and native decoder calls are isolated and cancellable: startup deadline 30 seconds, frame/start request deadline 5 seconds, recognizer reset deadline 1 second. Cancellation or timeout during a native request terminates and joins the decoder process; a subsequent session reloads the model. Normal completed sessions keep it loaded.
- Microphone disconnection, callback status errors, absent frames for two seconds or queue overflow close the session safely. The UI re-enumerates devices and retries with a single retry timer. The existing name/host-API selection store remains in use across restarts. Stop cancels retries.
- Missing Vosk/model or incompatible setup produces a visible setup message and disables repeated retries until the user re-enables wake mode. There is no Whisper or online fallback.
- All inference is local. Model construction always supplies `model_path`; it never supplies language/name arguments that could cause an automatic download. Model files under `models/` are ignored by Git.
- Queued/current PCM bytearrays are zeroed, resampling state is released and recognizers are destroyed between listening sessions. Vosk/native/IPC temporary immutable copies are released but cannot be guaranteed forensically erased.
- Wake audio and command recordings are never saved. The former development recording-save method was removed, including its legacy environment opt-in. Production settings also explicitly disable saving.
- PDF extraction, document error codes, filesystem policies and HTTPS allowlists were not changed in this migration.

## Configuration and setup

```dotenv
VOXPILOT_WAKE_ENGINE=vosk
VOXPILOT_WAKE_PHRASE=hello
VOSK_MODEL_PATH=models/vosk-model-small-en-us-0.15
VOSK_SAMPLE_RATE=16000
```

The default display phrase remains Hello when no override exists. A configured phrase changes both the wake grammar and activation-consumption guard. Only Vosk with a 16 kHz decoder is accepted; an invalid configuration fails visibly instead of selecting another engine.

Install the updated requirements in the chosen Python 3.12 runtime. Vosk is pinned to **0.3.45**. Manually obtain and extract the small English model from the [official Vosk model catalog](https://alphacephei.com/vosk/models). The configured path must name its extracted local folder. Relative paths are based on the project root. Runtime does not download a model. See README for instructions.

## Changed files for this migration

Created:

- `app/voice/vosk_decoder.py` — reusable isolated native decoder and safe setup errors.
- `tests/test_vosk_decoder.py` — grammar, final-only recognition, model reuse, cancellation and native process lifecycle.
- `tests/test_vosk_ui.py` — setup/recovery UI, stale activation, microphone exclusion and real Qt command cycles.
- `MILESTONE6_VOICE_FIX_VERIFICATION.md` — this report.

Modified:

- `app/voice/wake_word.py` — replace Whisper wake windows with continuous streaming Vosk and shared microphone locking.
- `app/voice/recorder.py` — remove command recording-to-disk path.
- `app/ui/workers.py` — safe setup-error signal, configured activation text and cancellation recheck.
- `app/ui/main_window.py` — separate wake setup notice, retry timer, Vosk lifecycle, configurable label and sensitivity; remove wake-path Whisper cache/download check.
- `app/config.py` — engine, phrase, model directory and sample-rate configuration.
- `app/main.py` — wire independent Vosk wake and faster-whisper command paths, force in-memory audio.
- `requirements.txt` — pinned Vosk dependency.
- `.env.example` — Vosk setup values; remove obsolete wake-window/audio-save examples.
- `.gitignore` — exclude local model directories.
- `README.md` — setup, architecture, privacy and current limitations.
- `tests/test_wake_word.py` — replace obsolete Whisper wake tests with synthetic PCM streaming tests.
- `tests/test_transcriber.py` — verify command-model reuse and no Whisper load during Vosk wake detection.
- `tests/test_runtime.py` — update the obsolete Whisper wake fixture; retain existing Qt flow assertions.
- `tests/test_config.py` — configurable phrase and router-consumption guard.
- `tests/test_recorder.py` — prove no audio files are created even with the legacy save flag enabled.

Other uncommitted Milestone 6/PDF changes already in the working tree were preserved. They are not part of this voice migration's file list.

## Verification performed

Focused command (existing Python executable; temporary pypdf dependency from the earlier milestone supplied through PYTHONPATH):

```powershell
$env:PYTHONPATH = Join-Path $env:TEMP 'voxpilot-m6-test-deps'
.\.venv\Scripts\python.exe -m pytest tests/test_wake_word.py tests/test_vosk_decoder.py tests/test_vosk_ui.py tests/test_runtime.py tests/test_ui_voice_signals.py tests/test_recorder.py tests/test_transcriber.py tests/test_config.py tests/test_audio_devices.py tests/test_voice_controller.py tests/test_tts.py -q --tb=short
```

**144 passed, 1 warning in 2.21 seconds.** No failures or skips.

Complete suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

**542 passed, 1 warning in 16.45 seconds.** No failures or skips. This includes existing command, security, PDF and filesystem regression tests.

The warning is Python 3.12's `audioop` deprecation for native-rate conversion. Python 3.13 is not supported by this project and would require a replacement converter.

`git diff --check`: passed. Index remained empty; no staging or commit was performed.

Dependency smoke check: installed the official `vosk-0.3.45-py3-none-win_amd64.whl` and its dependencies into `%TEMP%/voxpilot-vosk-test-deps`, not the project virtual environment. Importing Vosk loaded its native Windows library successfully under Python 3.12, and Model/KaldiRecognizer were available. No actual model was loaded or downloaded.

Tests use synthetic PCM and mock microphone/Vosk APIs. The decoder protocol tests assert exactly one model construction across fresh recognizers, the exact grammar, no PartialResult/FinalResult use, buffer clearing and safe errors. A real spawned fake decoder verifies process persistence and teardown. Actual Qt-thread cycles exercise streaming-controller activation, closed microphone before acknowledgement, exactly one command capture/transcription, and wake resumption after both execution success and failure. Existing tests cover TTS waiting/cooldown, manual input exclusion, stale results, confirmation/selection pauses and preserved results.

## Manual acceptance — not performed in this run

1. Install the updated runtime dependency and manually extract the configured local Vosk model. Restart VoxPilot.
2. Enable wake mode with the usual microphone. Confirm Wake-word listening and that no Whisper download/cache check occurs just to listen.
3. Say Hello followed by a short pause. Confirm one acknowledgement, then Command listening after TTS/cooldown.
4. Say Open Google. Confirm one command transcription, normal safe execution and resumed Vosk listening; Hello must not appear in history.
5. Repeat with Hello Google, Hey Shyam and unrelated speech. Confirm they do not activate. Repeat quiet/noisy/normal/high-sensitivity tests and record any acoustic misses or false positives.
6. Run a PDF or directory-listing command through wake mode. Confirm the complete result stays visible after resumption. Test an unsupported/dangerous command and confirm existing rejection.
7. Use manual Microphone while wake mode is active. Confirm it waits for Vosk stream closure and captures once. Toggle wake mode repeatedly, including after detection, to check stale activation cancellation.
8. Press Stop during model loading, listening, acknowledgement, command recording, transcription and execution. Confirm cancellation without overlapping streams. Close during listening and confirm application/process exit.
9. Disconnect/reconnect the microphone. Confirm a visible recoverable notice, selection restoration and a single resumed listener. Restart the app and confirm the saved microphone selection.
10. Point the model setting at a missing folder. Confirm visible setup instructions, no download/fallback and no overwrite of the previous result.
11. Confirm no wake or command recordings are written to disk.

## Remaining limitations

- Live Vosk recognition accuracy, real microphone drivers, accents/noise, real TTS acoustics and live latency were not tested. No model was downloaded for this task; model setup and live acceptance remain manual.
- Exact matching constrains recognized text, not the original acoustic utterance. A constrained recognizer may still misrecognize unrelated speech as Hello. Finalization also requires a pause.
- The model is reused during normal operation. Cancellation/timeout during native processing intentionally kills the decoder for reliable shutdown, requiring a reload next time.
- Stateful conversion currently relies on Python 3.12 audioop; there is one expected deprecation warning in verification.
- Mutable buffers are cleared, but Python/native immutable copies and OS paging are outside cryptographic erasure guarantees.
- Private virtual environments were deliberately untouched. The normal runtime still needs the pinned Vosk package and manually installed model.

Implementation references: [official streaming microphone example](https://github.com/alphacep/vosk-api/blob/master/python/example/test_microphone.py), [Vosk Python API implementation](https://github.com/alphacep/vosk-api/blob/master/python/vosk/__init__.py), and [Vosk 0.3.45 package](https://pypi.org/project/vosk/0.3.45/).
