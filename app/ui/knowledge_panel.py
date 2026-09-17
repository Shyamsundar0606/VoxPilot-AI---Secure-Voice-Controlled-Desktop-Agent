"""Presentation only: all document access and model work stays in the command worker."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton, QTextEdit, QListWidget
from app.models import Status
from app.ui.workers import CommandWorker


class KnowledgePanel(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Local Knowledge'))
        self.root = QComboBox()
        self.root.addItem('Select an approved source', '')
        for key in ('desktop', 'documents', 'downloads'): self.root.addItem(key, key)
        layout.addWidget(self.root)
        self.count = QLabel('Indexed documents: load index to check')
        layout.addWidget(self.count)
        self.progress = QLabel('')
        window.knowledge_progress = self.progress
        layout.addWidget(self.progress)
        self.question = QLineEdit(); self.question.setMaxLength(1000)
        self.question.setPlaceholderText('Ask your indexed documents...')
        self.question.returnPressed.connect(lambda: self.action('ask'))
        layout.addWidget(self.question)
        buttons = QHBoxLayout(); self.controls = []
        for title, action in [('Load index / sources', 'list'), ('Index documents', 'index'), ('Refresh index', 'refresh'),
                              ('Ask', 'ask'), ('Clear index', 'clear')]:
            button = QPushButton(title); button.clicked.connect(lambda checked=False, action=action: self.action(action))
            buttons.addWidget(button); self.controls.append(button)
        self.cancel = QPushButton('Cancel'); self.cancel.clicked.connect(self.cancel_work); buttons.addWidget(self.cancel)
        layout.addLayout(buttons)
        self.answer = QTextEdit(); self.answer.setReadOnly(True); self.answer.setMaximumHeight(180)
        self.sources = QListWidget(); self.sources.setMaximumHeight(120)
        self.excerpt = QTextEdit(); self.excerpt.setReadOnly(True); self.excerpt.setMaximumHeight(100)
        self.sources.currentRowChanged.connect(self.show_excerpt)
        self.source_rows = []
        self.open_button = QPushButton('Open selected approved source'); self.open_button.clicked.connect(self.open_source)
        self.controls.append(self.open_button)
        for widget in (self.answer, self.sources, self.excerpt, self.open_button): layout.addWidget(widget)

    def set_busy(self, busy):
        for control in self.controls: control.setEnabled(not busy)
        self.root.setEnabled(not busy); self.question.setEnabled(not busy)
        self.cancel.setEnabled(busy or self.window._confirmation is not None or self.window._document_selection is not None)

    def action(self, action):
        window = self.window
        if window._active_thread or window._voice_thread or window._tts_pending: return
        if action == 'index' and not self.root.currentData():
            self.progress.setText('Select one approved source first.'); return
        if action == 'ask' and not self.question.text().strip(): return
        command = {'index': 'Index documents in ' + str(self.root.currentData()),
                   'list': 'Show indexed documents', 'refresh': 'Refresh my document index',
                   'ask': 'Ask my documents: ' + self.question.text(), 'clear': 'Clear the document index'}[action]
        window.input.setText(command); window.execute_command()

    def complete(self, result):
        self.progress.setText(result.result_message[:200] if result.status != Status.COMPLETED else '')
        data = result.knowledge_data or {}
        if 'count' in data: self.count.setText(f"Indexed documents: {data['count']}")
        if 'roots' in data:
            selected = self.root.currentData(); self.root.clear(); self.root.addItem('Select an approved source', '')
            for key in data['roots']: self.root.addItem(key, key)
            self.root.setCurrentIndex(max(0, self.root.findData(selected)))
        if 'answer' in data: self.answer.setPlainText(data['answer'])
        if 'sources' in data:
            self.source_rows = data['sources']; self.sources.clear(); self.excerpt.clear()
            self.sources.addItems([row['label'] for row in self.source_rows])

    def show_excerpt(self, number):
        self.excerpt.setPlainText(self.source_rows[number]['excerpt'] if 0 <= number < len(self.source_rows) else '')

    def cancel_work(self):
        window = self.window
        if getattr(window._active_worker, 'source', None) == 'knowledge':
            window._active_worker.cancel_event.set()
            window._active_thread.requestInterruption()
            if window.executor.knowledge: window.executor.knowledge.cancel()
            self.progress.setText('Cancelling knowledge operation...')
        else:
            window._cancel_confirmation('Index action cancelled.')
            window._cancel_pdf_selection('Index selection cancelled.')

    def open_source(self):
        window, number = self.window, self.sources.currentRow()
        if window._active_thread or window._voice_thread or window._tts_pending or not 0 <= number < len(self.source_rows): return
        if window._wake_thread is not None:
            window._pending_action = 'knowledge_open'
            window._set_busy_controls(); window._stop_wake_listener()
            return
        window._cancel_confirmation(resume=False); window._cancel_pdf_selection(resume=False)
        window._cancelled = False; window._set_busy_controls(); window._set_status(Status.PROCESSING)
        window._launch_command_worker(CommandWorker(window.executor, '[Open approved citation]', knowledge_open=self.source_rows[number]['chunk_id']))
