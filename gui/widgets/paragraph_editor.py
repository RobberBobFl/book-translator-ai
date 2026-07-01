"""Paragraph editor widget for interactive / hybrid mode review."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ParagraphEditor(QWidget):
    """Shows original + editable translation; emit signals to accept or reject."""

    accepted = pyqtSignal(str)   # edited text
    rejected = pyqtSignal()      # keep original model translation

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Original text (read-only)
        orig_label = QLabel("Оригинал:")
        orig_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(orig_label)

        self._orig_text = QPlainTextEdit()
        self._orig_text.setReadOnly(True)
        self._orig_text.setMaximumHeight(200)
        layout.addWidget(self._orig_text)

        # Translation (editable)
        trans_label = QLabel("Перевод:")
        trans_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(trans_label)

        self._trans_text = QPlainTextEdit()
        self._trans_text.setMinimumHeight(100)
        layout.addWidget(self._trans_text)

        # Buttons
        btn_row = QHBoxLayout()
        self._accept_btn = QPushButton("✅ Принять")
        self._accept_btn.clicked.connect(self._on_accept)
        self._reject_btn = QPushButton("↩️ Оставить как есть")
        self._reject_btn.clicked.connect(self._on_reject)
        btn_row.addStretch()
        btn_row.addWidget(self._accept_btn)
        btn_row.addWidget(self._reject_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_content(self, original: str, translation: str) -> None:
        self._orig_text.setPlainText(original)
        self._trans_text.setPlainText(translation)
        self._trans_text.setFocus()

    def get_edited_text(self) -> str:
        return self._trans_text.toPlainText()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        self.accepted.emit(self._trans_text.toPlainText())

    def _on_reject(self) -> None:
        self.rejected.emit()
