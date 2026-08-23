from __future__ import annotations

from pathlib import Path

from app.database.connection import connect
from app.models import ExecutionResult


class HistoryRepository:
    def __init__(self, path: Path | str):
        self.path = path
        self.initialize()

    def initialize(self) -> None:
        with connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS command_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, original_command TEXT NOT NULL,
                normalized_command TEXT NOT NULL, selected_tool TEXT, status TEXT NOT NULL,
                result_message TEXT NOT NULL, error_message TEXT, created_timestamp TEXT NOT NULL,
                execution_duration INTEGER NOT NULL)""")

    def add(self, result: ExecutionResult) -> int:
        with connect(self.path) as db:
            cursor = db.execute("""INSERT INTO command_history
                (original_command, normalized_command, selected_tool, status, result_message, error_message, created_timestamp, execution_duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (result.original_command, result.normalized_command, result.selected_tool, result.status.value, result.result_message, result.error_message, result.created_at.isoformat(), result.duration_ms))
            return int(cursor.lastrowid)

    def recent(self, limit: int = 50) -> list[dict]:
        safe_limit = max(1, min(limit, 200))
        with connect(self.path) as db:
            rows = db.execute("SELECT * FROM command_history ORDER BY id DESC LIMIT ?", (safe_limit,)).fetchall()
        return [dict(row) for row in rows]

