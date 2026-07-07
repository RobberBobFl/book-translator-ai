"""Page editor widget for interactive / hybrid mode review."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PageEditor(QWidget):
    """Shows original + editable translation; emit signals for user actions."""

    accepted = pyqtSignal(str)   # edited text
    rejected = pyqtSignal()      # keep original model translation
    back_requested = pyqtSignal()
    skip_requested = pyqtSignal()
    rephrase_requested = pyqtSignal()
    translate_requested = pyqtSignal(int)  # (page index)

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
        self._orig_text.setMaximumHeight(180)
        layout.addWidget(self._orig_text)

        # Translation (editable)
        trans_label = QLabel("Перевод:")
        trans_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(trans_label)

        self._trans_text = QPlainTextEdit()
        self._trans_text.setMinimumHeight(80)
        layout.addWidget(self._trans_text)

        # Navigation buttons row
        nav_row = QHBoxLayout()
        self._back_btn = QPushButton("◀ Назад")
        self._back_btn.clicked.connect(self._on_back)
        nav_row.addWidget(self._back_btn)

        self._skip_btn = QPushButton("⏭ Пропустить")
        self._skip_btn.clicked.connect(self._on_skip)
        nav_row.addWidget(self._skip_btn)

        nav_row.addStretch()

        self._rephrase_btn = QPushButton("🔄 Перефразировать")
        self._rephrase_btn.clicked.connect(self._on_rephrase)
        nav_row.addWidget(self._rephrase_btn)

        self._translate_btn = QPushButton("🌐 Перевести")
        self._translate_btn.clicked.connect(self._on_translate)
        nav_row.addWidget(self._translate_btn)

        self._next_btn = QPushButton("Далее ▶")
        self._next_btn.setDefault(True)
        self._next_btn.clicked.connect(self._on_next)
        nav_row.addWidget(self._next_btn)

        layout.addLayout(nav_row)

        # Accept / Reject row
        action_row = QHBoxLayout()
        action_row.addStretch()
        self._accept_btn = QPushButton("✅ Принять")
        self._accept_btn.clicked.connect(self._on_accept)
        self._reject_btn = QPushButton("↩️ Оставить как есть")
        self._reject_btn.clicked.connect(self._on_reject)
        action_row.addWidget(self._accept_btn)
        action_row.addWidget(self._reject_btn)
        layout.addLayout(action_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_content(self, original: str, translation: str, review_idx: int | None = None) -> None:
        self._orig_text.setPlainText(original)
        self._trans_text.setPlainText(translation)
        self._trans_text.setFocus()
        self._current_review_idx = review_idx

    @property
    def current_review_idx(self) -> int | None:
        return self._current_review_idx

    def get_edited_text(self) -> str:
        return self._trans_text.toPlainText()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        self.accepted.emit(self._trans_text.toPlainText())

    def _on_reject(self) -> None:
        self.rejected.emit()

    def _on_next(self) -> None:
        self.accepted.emit(self._trans_text.toPlainText())

    def _on_skip(self) -> None:
        self.skip_requested.emit()

    def _on_back(self) -> None:
        self.back_requested.emit()

    def _on_rephrase(self) -> None:
        self.rephrase_requested.emit()

    def _on_translate(self) -> None:
        self.translate_requested.emit(self._current_review_idx)
