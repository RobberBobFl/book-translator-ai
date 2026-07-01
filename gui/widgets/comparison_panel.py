"""Comparison panel — side-by-side view with diff highlighting."""

import difflib

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from state.database import Database


class ComparisonPanel(QWidget):
    """Side-by-side comparison of two translations with diff highlighting."""

    _ADD_COLOR = QColor(200, 255, 200)
    _DEL_COLOR = QColor(255, 200, 200)
    _BOTH_COLOR = QColor(230, 230, 255)

    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db

        self._book_map: dict[str, int] = {}  # title -> book_id
        self._trans_map_a: dict[str, int] = {}
        self._trans_map_b: dict[str, int] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        # -- Controls ----------------------------------------------------
        ctrl_row = QHBoxLayout()

        ctrl_row.addWidget(QLabel("Книга:"))
        self._book_combo = QComboBox()
        self._book_combo.currentTextChanged.connect(self._on_book_changed)
        ctrl_row.addWidget(self._book_combo)

        ctrl_row.addSpacing(16)
        ctrl_row.addWidget(QLabel("Translation A:"))
        self._trans_a_combo = QComboBox()
        ctrl_row.addWidget(self._trans_a_combo)

        ctrl_row.addSpacing(16)
        ctrl_row.addWidget(QLabel("Translation B:"))
        self._trans_b_combo = QComboBox()
        ctrl_row.addWidget(self._trans_b_combo)

        ctrl_row.addSpacing(16)
        self._compare_btn = QPushButton("Сравнить")
        self._compare_btn.clicked.connect(self._on_compare)
        ctrl_row.addWidget(self._compare_btn)

        ctrl_row.addStretch()
        outer.addLayout(ctrl_row)

        # -- Diff display ------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        side_a = QWidget()
        a_layout = QVBoxLayout(side_a)
        self._title_a = QLabel("Model A")
        self._title_a.setStyleSheet("font-weight: bold; font-size: 14px;")
        a_layout.addWidget(self._title_a)
        self._text_a = QPlainTextEdit()
        self._text_a.setReadOnly(True)
        self._text_a.setTabStopDistance(20)
        a_layout.addWidget(self._text_a)
        splitter.addWidget(side_a)

        side_b = QWidget()
        b_layout = QVBoxLayout(side_b)
        self._title_b = QLabel("Model B")
        self._title_b.setStyleSheet("font-weight: bold; font-size: 14px;")
        b_layout.addWidget(self._title_b)
        self._text_b = QPlainTextEdit()
        self._text_b.setReadOnly(True)
        self._text_b.setTabStopDistance(20)
        b_layout.addWidget(self._text_b)
        splitter.addWidget(side_b)

        outer.addWidget(splitter, 1)

        self._refresh_book_list()

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload book list (call after a new translation completes)."""
        self._refresh_book_list()

    def _refresh_book_list(self) -> None:
        self._book_combo.blockSignals(True)
        current = self._book_combo.currentText()
        self._book_combo.clear()
        self._book_map.clear()
        for book in self._db.list_books():
            label = f"{book.title}  (id={book.id})"
            self._book_combo.addItem(label)
            self._book_map[label] = book.id
        if current and current in self._book_combo:
            self._book_combo.setCurrentText(current)
        self._book_combo.blockSignals(False)

    def _on_book_changed(self, label: str) -> None:
        self._refresh_trans_combos(label)

    def _refresh_trans_combos(self, book_label: str) -> None:
        book_id = self._book_map.get(book_label)
        if book_id is None:
            return

        trans = self._db.list_translations(book_id)

        self._trans_a_combo.blockSignals(True)
        self._trans_b_combo.blockSignals(True)
        self._trans_a_combo.clear()
        self._trans_b_combo.clear()
        self._trans_map_a.clear()
        self._trans_map_b.clear()

        for t in trans:
            label = f"{t.name}  (id={t.id}, {t.model_id or '?'})"
            self._trans_a_combo.addItem(label)
            self._trans_b_combo.addItem(label)
            self._trans_map_a[label] = t.id
            self._trans_map_b[label] = t.id

        self._trans_a_combo.blockSignals(False)
        self._trans_b_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------

    def _on_compare(self) -> None:
        book_label = self._book_combo.currentText()
        book_id = self._book_map.get(book_label)
        if book_id is None:
            return

        label_a = self._trans_a_combo.currentText()
        label_b = self._trans_b_combo.currentText()
        tid_a = self._trans_map_a.get(label_a)
        tid_b = self._trans_map_b.get(label_b)

        if tid_a is None or tid_b is None:
            return
        if tid_a == tid_b:
            return

        paras_a = self._db.get_paragraphs(tid_a)
        paras_b = self._db.get_paragraphs(tid_b)

        text_a = "\n\n".join(
            p.translated_text or "" for p in paras_a
        )
        text_b = "\n\n".join(
            p.translated_text or "" for p in paras_b
        )

        self._title_a.setText(f"Model A — {label_a}")
        self._title_b.setText(f"Model B — {label_b}")

        self._show_diff(text_a, text_b)

    def _show_diff(self, text_a: str, text_b: str) -> None:
        lines_a = text_a.splitlines(keepends=True)
        lines_b = text_b.splitlines(keepends=True)

        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)

        self._text_a.clear()
        self._text_b.clear()

        cursor_a = self._text_a.textCursor()
        cursor_b = self._text_b.textCursor()

        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            chunk_a = "".join(lines_a[i1:i2])
            chunk_b = "".join(lines_b[j1:j2])

            if op == "equal":
                self._append_text(cursor_a, chunk_a, None)
                self._append_text(cursor_b, chunk_b, None)
            elif op == "replace":
                self._append_text(cursor_a, chunk_a, self._DEL_COLOR)
                self._append_text(cursor_b, chunk_b, self._ADD_COLOR)
            elif op == "delete":
                self._append_text(cursor_a, chunk_a, self._DEL_COLOR)
                self._append_text(cursor_b, "", self._DEL_COLOR)
            elif op == "insert":
                self._append_text(cursor_a, "", self._ADD_COLOR)
                self._append_text(cursor_b, chunk_b, self._ADD_COLOR)

        # Scroll to top
        self._text_a.moveCursor(QTextCursor.MoveOperation.Start)
        self._text_b.moveCursor(QTextCursor.MoveOperation.Start)

    @staticmethod
    def _append_text(
        cursor: QTextCursor,
        text: str,
        color: QColor | None,
    ) -> None:
        if color is not None:
            fmt = cursor.charFormat()
            fmt.setBackground(color)
            cursor.insertText(text, fmt)
        else:
            cursor.insertText(text)
