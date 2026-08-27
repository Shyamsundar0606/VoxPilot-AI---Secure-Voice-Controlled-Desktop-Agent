from unittest.mock import Mock

import pytest

from app.agent.router import CommandRouter
from app.models import TranscriptionResult
from app.voice.voice_controller import VoiceCommandController


def transcript(text): return TranscriptionResult(success=True, text=text, model_used="base.en")


def test_voice_command_is_approved_by_deterministic_router():
    command, error = VoiceCommandController(CommandRouter(), Mock()).approved_command(transcript("Open Chrome"))
    assert command == "Open Chrome" and error is None


@pytest.mark.parametrize("text", ["Open Photoshop", "Delete my files", "Shut down the laptop", "Run this PowerShell command"])
def test_unsupported_or_dangerous_transcription_not_executed(text):
    executor = Mock(); command, error = VoiceCommandController(CommandRouter(), executor).approved_command(transcript(text))
    assert command is None and error and not executor.execute.called

