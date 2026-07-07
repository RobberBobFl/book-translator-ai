"""Book loader widget with drag-and-drop, file dialog, parsing and DB save."""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from loguru import logger

from core.models import Book
from state.database import Database
from utils.hash_utils import compute_file_hash
from parsers.base import BookParser
from parsers.txt_parser import TxtParser


# ---------------------------------------------------------------------------
# Parser factory
# ---------------------------------------------------------------------------

_PARSERS: dict[str, type[BookParser]] = {
    "txt": TxtParser,
}

SUPPORTED_FORMATS = sorted(_PARSERS.keys())


def _get_parser(ext: str) -> BookParser | None:
    cls = _PARSERS.get(ext)
    return cls() if cls is not None else None


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------


class BookLoaderWidget(QWidget):
    """Widget that handles book file loading via drag-drop or file dialog.

    Emits:
        book_loaded(book_id):  called after a book is successfully parsed
            and saved to the database.
    """

    book_loaded = pyqtSignal(int)

    def __init__(self, database: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = database
        self._current_book: Book | None = None

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Drop zone
        self._drop_label = QLabel(
            "📂  Перетащите файл книги сюда\n"
            "или воспользуйтесь кнопкой «Открыть файл»"
        )
        self._drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_label.setMinimumHeight(160)
        self._drop_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._drop_label.setStyleSheet(self._drop_stylesheet(False))
        self._drop_label.setWordWrap(True)
        layout.addWidget(self._drop_label)

        # Open button
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._open_btn = QPushButton("📂  Открыть файл...")
        self._open_btn.setMinimumHeight(36)
        self._open_btn.clicked.connect(self._on_open_clicked)
        btn_row.addWidget(self._open_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Book info section
        self._info_form = QFormLayout()
        self._info_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._title_label = QLabel("")
        self._chapters_label = QLabel("")
        self._pages_label = QLabel("")
        self._paragraphs_label = QLabel("")
        self._format_label = QLabel("")

        for label, widget in [
            ("Название:", self._title_label),
            ("Глав:", self._chapters_label),
            ("Страниц:", self._pages_label),
            ("Всего символов:", self._paragraphs_label),
            ("Формат:", self._format_label),
        ]:
            self._info_form.addRow(label, widget)
            widget.setVisible(False)

        self._legacy_warning = QLabel(
            "⚠️  Книга загружена в старой версии — страницы отсутствуют.\n"
            "Перезагрузите файл для работы с новой версией."
        )
        self._legacy_warning.setStyleSheet(
            "color: #e67e22; font-weight: bold; padding: 8px;"
            " background-color: #fef9e7; border: 1px solid #f5cba7;"
            " border-radius: 6px;"
        )
        self._legacy_warning.setWordWrap(True)
        self._legacy_warning.setVisible(False)
        layout.addWidget(self._legacy_warning)

        self._drop_label.setVisible(True)
        layout.addLayout(self._info_form)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        if event is None:
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drop_label.setStyleSheet(self._drop_stylesheet(True))

    def dragMoveEvent(self, event: QDragEnterEvent | None) -> None:
        if event is None:
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drop_label.setStyleSheet(self._drop_stylesheet(False))

    def dropEvent(self, event: QDropEvent | None) -> None:
        self._drop_label.setStyleSheet(self._drop_stylesheet(False))
        if event is None:
            return
        urls = event.mimeData().urls()
        if urls:
            local_path = urls[0].toLocalFile()
            if local_path:
                self._load_file(local_path)

    # ------------------------------------------------------------------
    # File dialog
    # ------------------------------------------------------------------

    def _on_open_clicked(self) -> None:
        filter_str = "Текст (*.txt);;Все файлы (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл книги", "", filter_str,
        )
        if path:
            self._load_file(path)

    # ------------------------------------------------------------------
    # Core load logic
    # ------------------------------------------------------------------

    def _load_file(self, file_path: str) -> None:
        path = Path(file_path)
        ext = path.suffix.lower().lstrip(".")

        if ext not in _PARSERS:
            QMessageBox.warning(
                self,
                "Неподдерживаемый формат",
                f"Файлы .{ext} не поддерживаются.\n"
                f"Доступные форматы: {', '.join(SUPPORTED_FORMATS)}",
            )
            return

        # Check hash for existing book
        file_hash = compute_file_hash(file_path)
        existing = self._db.get_book_by_path(file_path)
        if existing is not None and existing.file_hash != file_hash:
            answer = QMessageBox.question(
                self,
                "Файл изменился",
                "Этот файл уже загружался, но его содержимое изменилось.\n"
                "Начать заново?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._db.delete_book(existing.id)
            else:
                return
        elif existing is not None and existing.file_hash == file_hash:
            # Same file, just re-load
            self._show_book_info(existing)
            self.book_loaded.emit(existing.id)
            return

        # Parse
        parser = _get_parser(ext)
        if parser is None:
            QMessageBox.critical(self, "Ошибка", f"Не удалось найти парсер для .{ext}")
            return

        try:
            book = parser.parse(file_path)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Ошибка парсинга",
                f"Не удалось прочитать файл:\n{exc}",
            )
            return

        logger.info(f"Загружена книга: {book.title}")
        logger.info(f"Глав: {len(book.chapters)}")
        logger.info(f"Страниц: {len(book.pages)}")
        if book.pages:
            logger.info(f"Всего символов: {sum(len(p.original_text) for p in book.pages)}")

        if not book.pages:
            QMessageBox.warning(
                self,
                "Пустая книга",
                "Файл не содержит текста для перевода.\n"
                "Проверьте содержимое файла.",
            )
            return

        # Save to DB
        try:
            book = self._db.save_book(book)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Ошибка БД",
                f"Не удалось сохранить книгу в базу:\n{exc}",
            )
            return

        saved_count = sum(1 for p in book.pages if p.id != 0) if book.id else 0
        logger.info(f"Сохранено в БД: {saved_count} страниц")
        if saved_count != len(book.pages):
            logger.error(
                f"ПОТЕРЯ ДАННЫХ! В книге {len(book.pages)} страниц, "
                f"в БД {saved_count}"
            )

        self._show_book_info(book)
        self.book_loaded.emit(book.id)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _show_book_info(self, book: Book) -> None:
        self._current_book = book

        self._title_label.setText(book.title)
        self._chapters_label.setText(str(len(book.chapters)))
        self._pages_label.setText(str(len(book.pages)) if book.pages else "—")
        self._paragraphs_label.setText(
            str(sum(len(p.original_text) for p in book.pages)) if book.pages else "—"
        )
        self._format_label.setText(book.source_format.upper())

        for widget in [
            self._title_label,
            self._chapters_label,
            self._pages_label,
            self._paragraphs_label,
            self._format_label,
        ]:
            widget.setVisible(True)

        self._drop_label.setText(
            f"✅  Загружено: {book.title}\n"
            f"{len(book.chapters)} глав, {len(book.pages) if book.pages else 0} страниц"
        )
        self._drop_label.setStyleSheet(self._drop_stylesheet(False, loaded=True))

        # Legacy warning: old books loaded without pages
        self._legacy_warning.setVisible(not book.pages)

    @staticmethod
    def _drop_stylesheet(hover: bool = False, loaded: bool = False) -> str:
        if loaded:
            return (
                "border: 2px dashed #2ecc71; border-radius: 10px;"
                " background-color: #eafaf1; padding: 20px; font-size: 14px;"
            )
        if hover:
            return (
                "border: 2px dashed #3498db; border-radius: 10px;"
                " background-color: #ebf5fb; padding: 20px; font-size: 14px; color: #2c3e50;"
            )
        return (
            "border: 2px dashed #bdc3c7; border-radius: 10px;"
            " background-color: #f8f9fa; padding: 20px; font-size: 14px; color: #7f8c8d;"
        )
