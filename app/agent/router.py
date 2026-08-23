from __future__ import annotations

import re

from app.models import RoutedCommand, ToolRequest


def normalize_command(command: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", command.lower()).strip()


APP_ALIASES = {
    "chrome": "chrome", "google chrome": "chrome", "spotify": "spotify",
    "settings": "settings", "windows settings": "settings", "notepad": "notepad",
    "microsoft word": "word", "word": "word", "calculator": "calculator",
    "vs code": "vscode", "visual studio code": "vscode", "file explorer": "file_explorer",
}


class CommandRouter:
    def route(self, command: str) -> RoutedCommand:
        normalized = normalize_command(command)
        base = {"original_command": command, "normalized_command": normalized}
        if not normalized:
            return RoutedCommand(**base, supported=False, response="Please enter a command.")
        if normalized in {"what time is it", "tell me the time", "what is the time", "current time"}:
            return self._tool(base, "current_time")
        if normalized in {"what is today s date", "what is todays date", "today s date", "todays date", "current date"}:
            return self._tool(base, "current_date")
        if normalized in {"check battery percentage", "what is my battery percentage", "battery percentage", "check my battery"}:
            return self._tool(base, "battery_status")
        if normalized in {"check available storage", "how much storage is available", "available storage", "check storage"}:
            return self._tool(base, "storage_status")
        if normalized in {"help", "what can you do", "show help"}:
            return self._tool(base, "help")
        if normalized in {"open chatgpt", "open chat gpt"}:
            return self._tool(base, "open_url", url_name="chatgpt")
        if normalized in {"open chatgpt in chrome", "open chat gpt in chrome"}:
            return self._tool(base, "open_url", url_name="chatgpt")
        if normalized.startswith(("open ", "launch ", "start ")):
            target = re.sub(r"^(open|launch|start) ", "", normalized)
            app = APP_ALIASES.get(target)
            if app:
                return self._tool(base, "open_application", application=app)
            return RoutedCommand(**base, supported=False, response="That application is not available in the approved application list.")
        return RoutedCommand(**base, supported=False, response="I cannot safely perform that command. Say 'Help' to see approved commands.")

    @staticmethod
    def _tool(base: dict[str, str], name: str, **arguments: str) -> RoutedCommand:
        return RoutedCommand(**base, supported=True, tool_request=ToolRequest(tool_name=name, arguments=arguments))

