from unittest.mock import patch

import requests

from app.agent.ollama_client import OllamaClient


def test_ollama_unavailable_returns_none_for_deterministic_fallback():
    client = OllamaClient("http://localhost:11434", "qwen3:latest", "llama3.2:3b", timeout=0.01)
    with patch.object(client, "complete", side_effect=ValueError("unavailable")):
        assert client.route("unknown request") is None
