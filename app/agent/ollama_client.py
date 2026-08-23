from __future__ import annotations

import json

import requests
from pydantic import ValidationError

from app.models import ToolRequest
from app.security.validators import PolicyViolation, validate_tool_request


class OllamaClient:
    def __init__(self, base_url: str, primary_model: str, fallback_model: str, timeout: float = 10):
        self.base_url, self.primary_model, self.fallback_model, self.timeout = base_url.rstrip("/"), primary_model, fallback_model, timeout

    def route(self, command: str) -> ToolRequest | None:
        prompt = "/no_think Return only JSON with tool_name and arguments. Use only approved tools. Command: " + command
        for model in (self.primary_model, self.fallback_model):
            try:
                response = requests.post(f"{self.base_url}/api/generate", json={"model": model, "prompt": prompt, "stream": False, "format": "json"}, timeout=self.timeout)
                response.raise_for_status()
                request = ToolRequest.model_validate(json.loads(response.json()["response"]))
                validate_tool_request(request)
                return request
            except (requests.RequestException, KeyError, ValueError, ValidationError, PolicyViolation):
                continue
        return None

