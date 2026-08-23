from datetime import datetime
from types import SimpleNamespace

from app.tools.system_tools import SystemTools


class FakePsutil:
    @staticmethod
    def sensors_battery(): return SimpleNamespace(percent=72.2, power_plugged=True)
    @staticmethod
    def disk_usage(_path): return SimpleNamespace(free=20 * 1024 ** 3)


def test_time_and_date():
    tools = SystemTools(now_provider=lambda: datetime(2026, 8, 23, 18, 30), psutil_module=FakePsutil)
    assert tools.current_time().message == "The current time is 6:30 PM."
    assert "Sunday, August 23, 2026" in tools.current_date().message


def test_mocked_battery_and_storage():
    tools = SystemTools(psutil_module=FakePsutil)
    assert tools.battery_status().message == "Your battery is at 72 percent and is charging."
    assert tools.storage_status().message == "You have 20.0 GB of storage available."


def test_missing_battery_is_safe():
    fake = SimpleNamespace(sensors_battery=lambda: None)
    assert not SystemTools(psutil_module=fake).battery_status().success

