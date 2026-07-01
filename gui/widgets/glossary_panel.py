"""Glossary management panel — table, add/delete, auto-detect, search."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.glossary import GlossaryManager
from core.models import Book, GlossaryEntry


class GlossaryPanel(QWidget):
    """Panel for viewing and editing glossary terms for a loaded book.

    Emits:
        glossary_updated(book_id): after any add/edit/delete/auto-detect.
    """

    glossary_updated = pyqtSignal(int)

    COL_ORIGINAL = 0
    COL_TRANSLATION = 1
    COL_AUTO = 2
    COL_ENTRY_ID = 3  # hidden

    def __init__(self, glossary_manager: GlossaryManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._gm = glossary_manager
        self._current_book_id: int | None = None
        self._current_book: Book | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Search
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("🔍 Поиск:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Фильтр терминов...")
        self._search_input.textChanged.connect(self._filter_table)
        search_row.addWidget(self._search_input)
        layout.addLayout(search_row)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Термин", "Перевод", "Авто", ""])
        self._table.setColumnHidden(self.COL_ENTRY_ID, True)
        self._table.horizontalHeader().setSectionResizeMode(
            self.COL_ORIGINAL, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            self.COL_TRANSLATION, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            self.COL_AUTO, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.itemChanged.connect(self._on_cell_changed)
        layout.addWidget(self._table)

        # Buttons
        btn_row = QHBoxLayout()

        self._auto_btn = QPushButton("🔍 Авто-детект")
        self._auto_btn.clicked.connect(self._on_auto_detect)
        self._auto_btn.setEnabled(False)
        btn_row.addWidget(self._auto_btn)

        self._add_btn = QPushButton("➕ Добавить")
        self._add_btn.clicked.connect(self._on_add)
        self._add_btn.setEnabled(False)
        btn_row.addWidget(self._add_btn)

        self._delete_btn = QPushButton("🗑️ Удалить")
        self._delete_btn.clicked.connect(self._on_delete)
        self._delete_btn.setEnabled(False)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Public API — called when a book is loaded
    # ------------------------------------------------------------------

    def load_book(self, book: Book) -> None:
        """Populate the panel with glossary entries for *book*."""
        self._current_book = book
        self._current_book_id = book.id
        self._auto_btn.setEnabled(True)
        self._add_btn.setEnabled(True)

        self._refresh_table()

    def clear(self) -> None:
        """Reset the panel when no book is loaded."""
        self._current_book_id = None
        self._current_book = None
        self._table.setRowCount(0)
        self._auto_btn.setEnabled(False)
        self._add_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        if self._current_book_id is None:
            return
        entries = self._gm.get_entries(self._current_book_id)
        self._populate_table(entries)

    def _populate_table(self, entries: list[GlossaryEntry]) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(entries))

        for row, entry in enumerate(entries):
            self._set_item(row, self.COL_ORIGINAL, entry.original_term)
            self._set_item(row, self.COL_TRANSLATION, entry.translated_term or "")
            self._set_item(row, self.COL_AUTO, "✓" if entry.is_auto_detected else "")
            self._set_item(row, self.COL_ENTRY_ID, str(entry.id) if entry.id else "")

        self._table.blockSignals(False)
        self._apply_filter()

    def _set_item(self, row: int, col: int, text: str) -> None:
        from PyQt6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text)
        if col in (GlossaryPanel.COL_AUTO, GlossaryPanel.COL_ENTRY_ID):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, col, item)

    # ------------------------------------------------------------------
    # Search filter
    # ------------------------------------------------------------------

    def _filter_table(self) -> None:
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._search_input.text().strip().lower()
        for row in range(self._table.rowCount()):
            original = self._table.item(row, self.COL_ORIGINAL)
            translation = self._table.item(row, self.COL_TRANSLATION)
            match = True
            if query:
                orig_text = (original.text() if original else "").lower()
                trans_text = (translation.text() if translation else "").lower()
                match = query in orig_text or query in trans_text
            self._table.setRowHidden(row, not match)

    # ------------------------------------------------------------------
    # Cell edit
    # ------------------------------------------------------------------

    def _on_cell_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != self.COL_TRANSLATION:
            return

        row = item.row()
        entry_id_item = self._table.item(row, self.COL_ENTRY_ID)
        if entry_id_item is None:
            return
        entry_id = int(entry_id_item.text())
        new_translation = item.text().strip()

        self._gm.update_entry(entry_id, new_translation)
        self._emit_updated()

    # ------------------------------------------------------------------
    # Auto-detect
    # ------------------------------------------------------------------

    def _on_auto_detect(self) -> None:
        if self._current_book is None or self._current_book_id is None:
            return

        answer = QMessageBox.question(
            self,
            "Авто-детект терминов",
            "Будут найдены имена собственные и частые термины. "
            "Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            new_entries = self._gm.auto_detect(self._current_book)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Авто-детект не удался:\n{exc}")
            return

        self._refresh_table()

        if new_entries:
            QMessageBox.information(
                self,
                "Готово",
                f"Найдено {len(new_entries)} новых терминов.\n"
                "Отредактируйте переводы в таблице.",
            )
        else:
            QMessageBox.information(
                self, "Готово", "Новых терминов не найдено."
            )
        self._emit_updated()

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        if self._current_book_id is None:
            return

        term, ok = QInputDialog.getText(
            self, "Добавить термин", "Оригинальный термин:"
        )
        if not ok or not term.strip():
            return

        translation, ok2 = QInputDialog.getText(
            self, "Перевод", f"Перевод для «{term.strip()}»:"
        )
        if not ok2:
            return

        self._gm.add_entry(
            book_id=self._current_book_id,
            original_term=term.strip(),
            translated_term=translation.strip() or None,
            is_auto_detected=False,
        )

        self._refresh_table()
        self._emit_updated()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _on_delete(self) -> None:
        current_row = self._table.currentRow()
        if current_row < 0:
            return

        entry_id_item = self._table.item(current_row, self.COL_ENTRY_ID)
        original_item = self._table.item(current_row, self.COL_ORIGINAL)
        if entry_id_item is None or original_item is None:
            return

        entry_id = int(entry_id_item.text())
        term = original_item.text()

        answer = QMessageBox.question(
            self,
            "Удалить термин",
            f'Удалить «{term}» из глоссария?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._gm.delete_entry(entry_id)
        self._refresh_table()
        self._emit_updated()

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def _emit_updated(self) -> None:
        if self._current_book_id is not None:
            self.glossary_updated.emit(self._current_book_id)
