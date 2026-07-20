"""Glossary management dialog for the current book."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.glossary import GlossaryManager
from gui import i18n as gui_i18n
from state.database import Database


class GlossaryDialog(QDialog):
    """Manage per-book glossary terms (original → translation).

    Terms with a filled translation are injected into the translation
    prompt by :class:`~core.glossary.GlossaryManager` on every page, so
    changes made here take effect for the next translated pages immediately.
    """

    def __init__(self, db: Database, book_id: int, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._book_id = book_id
        self._mgr = GlossaryManager(db)
        self._book = db.load_book(book_id)
        self.setMinimumSize(540, 440)
        self._build_ui()
        self.retranslate_ui()
        self._refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 3)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        self._auto_btn = QPushButton()
        self._auto_btn.clicked.connect(self._on_auto)
        self._add_btn = QPushButton()
        self._add_btn.clicked.connect(self._on_add)
        self._del_btn = QPushButton()
        self._del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._auto_btn)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        self._close_btn = QPushButton()
        self._close_btn.setDefault(True)
        self._close_btn.clicked.connect(self.accept)
        close_row.addWidget(self._close_btn)
        layout.addLayout(close_row)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for e in self._mgr.get_entries(self._book_id):
            row = self._table.rowCount()
            self._table.insertRow(row)

            term = QTableWidgetItem(e.original_term)
            term.setFlags(term.flags() & ~Qt.ItemFlag.ItemIsEditable)
            term.setData(Qt.ItemDataRole.UserRole, e.id)

            trans = QTableWidgetItem(e.translated_term or "")

            auto = QTableWidgetItem(
                gui_i18n.tr("gl.auto_yes") if e.is_auto_detected else gui_i18n.tr("gl.auto_no")
            )
            auto.setFlags(auto.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self._table.setItem(row, 0, term)
            self._table.setItem(row, 1, trans)
            self._table.setItem(row, 2, auto)
        self._table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        term_item = self._table.item(item.row(), 0)
        if term_item is None:
            return
        entry_id = term_item.data(Qt.ItemDataRole.UserRole)
        if entry_id is None:
            return
        self._mgr.update_entry(entry_id, item.text().strip())

    def _on_auto(self) -> None:
        if self._book is None:
            return
        created = self._mgr.auto_detect(self._book)
        self._refresh()
        QMessageBox.information(
            self,
            gui_i18n.tr("gl.auto"),
            gui_i18n.tr("gl.detected", n=len(created)),
        )

    def _on_add(self) -> None:
        dlg = _AddTermDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            term, trans = dlg.get_data()
            term = term.strip()
            if not term:
                return
            self._mgr.add_entry(self._book_id, term, trans.strip() or None)
            self._refresh()

    def _on_delete(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        term_item = self._table.item(row, 0)
        if term_item is None:
            return
        entry_id = term_item.data(Qt.ItemDataRole.UserRole)
        if entry_id is None:
            return
        answer = QMessageBox.question(
            self,
            gui_i18n.tr("gl.delete_title"),
            gui_i18n.tr("gl.delete_text", term=term_item.text()),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._mgr.delete_entry(entry_id)
        self._refresh()

    # ------------------------------------------------------------------
    # Live retranslation
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        self.setWindowTitle(gui_i18n.tr("gl.title"))
        self._table.setHorizontalHeaderLabels([
            gui_i18n.tr("gl.term"),
            gui_i18n.tr("gl.translation"),
            gui_i18n.tr("gl.auto_col"),
        ])
        self._auto_btn.setText(gui_i18n.tr("gl.auto"))
        self._add_btn.setText(gui_i18n.tr("gl.add"))
        self._del_btn.setText(gui_i18n.tr("gl.delete"))
        self._close_btn.setText(gui_i18n.tr("gl.close"))


class _AddTermDialog(QDialog):
    """Small dialog to add a single glossary term + its translation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(gui_i18n.tr("gl.add"))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._term = QLineEdit()
        self._trans = QLineEdit()
        form.addRow(gui_i18n.tr("gl.term_label"), self._term)
        form.addRow(gui_i18n.tr("gl.translation_label"), self._trans)
        layout.addLayout(form)

        row = QHBoxLayout()
        row.addStretch()
        ok = QPushButton(gui_i18n.tr("sp.ok"))
        ok.clicked.connect(self.accept)
        cancel = QPushButton(gui_i18n.tr("sp.cancel"))
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def get_data(self) -> tuple[str, str]:
        return self._term.text(), self._trans.text()
