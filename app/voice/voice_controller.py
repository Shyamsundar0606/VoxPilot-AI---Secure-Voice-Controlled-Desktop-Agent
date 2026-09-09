from __future__ import annotations

from app.models import TranscriptionResult


class VoiceCommandController:
    def __init__(self, router, executor, allow_intent_planning=False):
        self.router, self.executor = router, executor
        self.allow_intent_planning = allow_intent_planning

    def approved_command(self, transcription: TranscriptionResult):
        if not transcription.success or not transcription.text.strip():
            return None, transcription.message
        if self.allow_intent_planning:
            # Preparation only: routing/planning/policy run in CommandWorker, never here on the UI thread.
            return transcription.text, None
        routed = self.router.route(transcription.text)
        if not routed.supported or routed.tool_request is None:
            return None, "The command was transcribed but is unsupported or ambiguous. Please repeat or type it."
        return transcription.text, None
