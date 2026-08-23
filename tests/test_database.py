from app.database.repository import HistoryRepository
from app.models import ExecutionResult, Status


def test_history_creation_and_retrieval(tmp_path):
    repository = HistoryRepository(tmp_path / "history.sqlite3")
    row_id = repository.add(ExecutionResult(original_command="Help", normalized_command="help", selected_tool="help", status=Status.COMPLETED, result_message="Supported commands"))
    rows = repository.recent()
    assert row_id == 1
    assert rows[0]["original_command"] == "Help"
    assert rows[0]["execution_duration"] == 0

