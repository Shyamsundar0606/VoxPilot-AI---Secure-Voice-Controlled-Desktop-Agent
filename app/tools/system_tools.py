from __future__ import annotations

from datetime import datetime
from pathlib import Path

import psutil

from app.models import ToolResult


class SystemTools:
    def __init__(self, now_provider=datetime.now, psutil_module=psutil, storage_path: Path | None = None):
        self.now_provider = now_provider
        self.psutil = psutil_module
        self.storage_path = storage_path or Path.home().anchor

    def current_time(self) -> ToolResult:
        value = self.now_provider().strftime("%I:%M %p").lstrip("0")
        return ToolResult(success=True, message=f"The current time is {value}.")

    def current_date(self) -> ToolResult:
        value = self.now_provider().strftime("%A, %B %d, %Y").replace(" 0", " ")
        return ToolResult(success=True, message=f"Today's date is {value}.")

    def battery_status(self) -> ToolResult:
        battery = self.psutil.sensors_battery()
        if battery is None:
            return ToolResult(success=False, message="Battery information is not available on this device.", error="Battery information unavailable")
        state = "charging" if battery.power_plugged else "not charging"
        return ToolResult(success=True, message=f"Your battery is at {round(battery.percent)} percent and is {state}.")

    def storage_status(self) -> ToolResult:
        usage = self.psutil.disk_usage(str(self.storage_path))
        free_gb = usage.free / (1024 ** 3)
        return ToolResult(success=True, message=f"You have {free_gb:.1f} GB of storage available.", data={"free_bytes": usage.free})

