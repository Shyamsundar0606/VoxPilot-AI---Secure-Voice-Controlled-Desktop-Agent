from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget


class MicrophoneSettings(QWidget):
    test_requested = Signal(object)
    sensitivity_changed = Signal(str)

    def __init__(self, device_service, parent=None):
        super().__init__(parent)
        self.device_service = device_service
        self.selector = QComboBox()
        self.refresh_button = QPushButton("Refresh microphones")
        self.test_button = QPushButton("Test microphone")
        self.sensitivity = QComboBox(); self.sensitivity.addItem("Normal sensitivity", "normal"); self.sensitivity.addItem("High sensitivity", "high")
        layout = QHBoxLayout(self)
        layout.addWidget(QLabel("Microphone:")); layout.addWidget(self.selector, 1)
        layout.addWidget(self.refresh_button); layout.addWidget(self.test_button)
        layout.addWidget(self.sensitivity)
        self.refresh_button.clicked.connect(self.refresh)
        self.test_button.clicked.connect(lambda: self.test_requested.emit(self.selected_device()))
        self.selector.currentIndexChanged.connect(self._save)
        self.sensitivity.currentIndexChanged.connect(lambda: self.sensitivity_changed.emit(self.sensitivity.currentData()))
        self.refresh()

    def refresh(self):
        devices = self.device_service.input_devices()
        selected = self.device_service.selected_device(devices)
        self.selector.blockSignals(True); self.selector.clear()
        for device in devices:
            suffix = " (default)" if device.is_default else ""
            rate = "16 kHz" if device.supports_16000 else f"{round(device.default_sample_rate)} Hz → 16 kHz"
            self.selector.addItem(f"{device.name} — {device.host_api_name} — {rate}{suffix}", device.identifier)
        if selected is not None:
            index = self.selector.findData(selected)
            self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)
        self.setToolTip("No input microphone is available." if not devices else "Select the microphone used for voice commands.")

    def selected_device(self) -> int | None:
        value = self.selector.currentData()
        return int(value) if value is not None else None

    def _save(self):
        self.device_service.save_selected(self.selected_device())
