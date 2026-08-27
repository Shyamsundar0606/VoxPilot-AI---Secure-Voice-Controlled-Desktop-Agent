from __future__ import annotations

from app.models import TranscriptionResult


class VoiceCommandController:
    def __init__(self, router, executor):
        self.router, self.executor = router, executor

    def approved_command(self, transcription: TranscriptionResult):
        if not transcription.success or not transcription.text.strip():
            return None, transcription.message
        routed = self.router.route(transcription.text)
        if not routed.supported or routed.tool_request is None:
            return None, "The command was transcribed but is unsupported or ambiguous. Please repeat or type it."
        return transcription.text, None
