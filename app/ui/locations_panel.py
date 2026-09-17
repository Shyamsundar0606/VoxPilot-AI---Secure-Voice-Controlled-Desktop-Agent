"""Explicit approval UI; filesystem work uses the retained command worker lifecycle."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QComboBox, QFileDialog, QMessageBox)
from app.ui.workers import ProjectRootWorker
from app.models import ExecutionResult, Status


class LocationsWorker(ProjectRootWorker):
    def __init__(self, roots, action, value=None, kind="document"):
        super().__init__(roots, value)
        self.source = "locations"
        self.action, self.kind = action, kind

    def run(self):
        data = None
        try:
            if self.cancel_event.is_set(): raise ValueError("Operation cancelled.")
            if self.action == "add": self.roots.add(self.path, self.kind, self.cancel_event)
            elif self.action == "remove": self.roots.remove(self.path, confirmed=True, cancel_event=self.cancel_event)
            elif self.action == "open":
                self.roots.platform.open_folder(self.roots.resolve(self.path))
            elif self.action != "refresh": raise ValueError("Unsupported location action.")
            data = {"locations": self.roots.locations()}
            message, status = "Approved locations updated.", Status.COMPLETED
        except (OSError, ValueError) as exc:
            message, status = str(exc), Status.FAILED
        except Exception:
            message, status = "Approved locations operation failed safely.", Status.FAILED
        self.finished.emit(ExecutionResult(original_command="[Approved Locations]", normalized_command="",
            selected_tool="approved_locations", status=status, result_message=message,
            knowledge_data=data, store_history=False))


class LocationsPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Approved Locations"))
        self.kind = QComboBox()
        self.kind.addItem("General document location", "document")
        self.kind.addItem("Projects location", "project")
        layout.addWidget(self.kind)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Identifier", "Folder name", "Full path", "Availability", "Approval type"])
        self.table.setMaximumHeight(160)
        layout.addWidget(self.table)
        self.message = QLabel("Refresh folders to load approved locations.")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.buttons = []
        for label, action in [("Add approved folder", "add"), ("Remove selected folder", "remove"),
                              ("Open selected folder", "open"), ("Refresh folders", "refresh")]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, action=action: self.action(action))
            self.buttons.append(button)
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def set_busy(self, busy):
        for button in self.buttons: button.setEnabled(not busy)
        self.kind.setEnabled(not busy)

    def action(self, action):
        window = self.window
        if (window._active_thread or window._voice_thread or window._wake_thread or
                window._tts_pending or window._close_pending or window.wake_toggle.isChecked()):
            self.message.setText("Stop listening and wait for the current operation before managing locations.")
            return
        from app.agent.executor import CommandExecutor
        if not isinstance(window.executor, CommandExecutor) or not window.executor.registry.filesystem: return
        value = None
        if action == "add":
            value = QFileDialog.getExistingDirectory(self, "Select a local folder to approve")
            if not value: return
        elif action in {"remove", "open"}:
            item = self.table.currentItem()
            if item is None:
                self.message.setText("Select an approved folder first.")
                return
            value = item.text(0)
            if action == "remove" and QMessageBox.question(self, "Remove folder approval?",
                    f"Remove {value}: {item.text(2)}?\nThe folder and its files will not be deleted. "
                    "Other approved parent or child folders remain accessible.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        window._cancel_confirmation(resume=False)
        window._cancel_pdf_selection(resume=False)
        window._cancelled = False
        window._set_busy_controls()
        window._launch_command_worker(LocationsWorker(window.executor.registry.filesystem.roots,
                                                      action, value, self.kind.currentData()))

    def complete(self, result):
        self.message.setText(result.result_message)
        rows = (result.knowledge_data or {}).get("locations")
        if rows is None: return
        self.table.clear()
        selector = self.window.knowledge_panel.root
        selected = selector.currentData()
        selector.clear()
        selector.addItem("Select an approved source", "")
        for row in rows:
            self.table.addTopLevelItem(QTreeWidgetItem([row[k] for k in ("id", "name", "path", "status", "type")]))
            from app.documents.policy import allowed_document_root
            if allowed_document_root(row['id']):
                selector.addItem(f"{row['id']} — {row['name']} ({row['status']})", row['id'])
        selector.setCurrentIndex(max(0, selector.findData(selected)))
