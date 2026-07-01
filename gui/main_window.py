"""Main application window — tabbed assembly, menu, resume dialog."""

from pathlib import Path

from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
)

from core.config import ConfigManager
from gui.widgets.book_loader import BookLoaderWidget
from utils.hash_utils import compute_file_hash
from gui.widgets.glossary_panel import GlossaryPanel
from gui.widgets.comparison_panel import ComparisonPanel
from gui.widgets.settings_panel import SettingsPanel
from gui.widgets.translation_panel import TranslationPanel
from state.database import Database
from translator.engine import TranslatorEngine

_CONFIG_DIR = Path.home() / ".config" / "book-translator"
_DB_PATH = _CONFIG_DIR / "books.db"


class MainWindow(QMainWindow):
    """Top-level window that assembles all panels into a tabbed layout."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Book Translator")
        self.setMinimumSize(1100, 700)

        # -- Core services -----------------------------------------------
        self._cfg = ConfigManager()
        self._db = Database(_DB_PATH)
        self._db.connect()
        self._db.initialize()
        self._engine = TranslatorEngine(self._cfg)

        # -- Panels ------------------------------------------------------
        from core.glossary import GlossaryManager
        self._book_loader = BookLoaderWidget(self._db)
        self._glossary_panel = GlossaryPanel(GlossaryManager(self._db))

        self._translation_panel = TranslationPanel(self._db, self._cfg, self._engine)
        self._comparison_panel = ComparisonPanel(self._db)
        self._settings_panel = SettingsPanel(self._cfg)

        # -- Tab widget --------------------------------------------------
        self._tabs = QTabWidget()
        self._tabs.addTab(self._book_loader, "📖 Книга")
        self._tabs.addTab(self._glossary_panel, "📖 Глоссарий")
        self._tabs.addTab(self._translation_panel, "🌐 Перевод")
        self._tabs.addTab(self._comparison_panel, "🆚 Сравнение")
        self._tabs.addTab(self._settings_panel, "⚙ Настройки")
        self.setCentralWidget(self._tabs)

        # -- Menu bar ----------------------------------------------------
        self._build_menu()

        # -- Status bar --------------------------------------------------
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Готов")

        # -- Hotkeys -----------------------------------------------------
        self._build_hotkeys()

        # -- Signal wiring -----------------------------------------------
        self._connect_signals()

        # -- Resume ------------------------------------------------------
        self._check_resume()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        # File menu
        file_menu = self.menuBar().addMenu("&Файл")

        open_action = QAction("&Открыть книгу...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._on_menu_open)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        quit_action = QAction("&Выход", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Help menu
        help_menu = self.menuBar().addMenu("&Справка")

        about_action = QAction("&О программе", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._book_loader.book_loaded.connect(self._on_book_loaded)
        self._translation_panel.translation_started.connect(
            lambda *_: self._comparison_panel.refresh()
        )
        self._translation_panel.translation_finished.connect(
            self._on_translation_finished
        )
        self._settings_panel.settings_changed.connect(
            self._translation_panel.refresh_models
        )

    def _on_book_loaded(self, book_id: int) -> None:
        book = self._db.load_book(book_id)
        if book is None:
            return
        self._glossary_panel.load_book(book)
        self._translation_panel.set_book(book_id)
        self._tabs.setCurrentWidget(self._translation_panel)
        self._status.showMessage(
            f"Загружено: {book.title}  |  "
            f"{len(book.chapters)} глав, "
            f"{sum(len(ch.paragraphs) for ch in book.chapters)} абзацев"
        )

    def _on_translation_finished(self) -> None:
        self._status.showMessage("Перевод завершён")

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _on_menu_open(self) -> None:
        self._book_loader._on_open_clicked()

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "Book Translator",
            "Batch translator for EPUB, FB2, PDF & TXT books\n"
            "using LLM APIs.\n\n"
            "Version 0.1.0\n"
            "https://github.com/example/book-translator",
        )

    # ------------------------------------------------------------------
    # Hotkeys
    # ------------------------------------------------------------------

    def _build_hotkeys(self) -> None:
        tp = self._translation_panel

        # Space — pause / resume
        QShortcut(QKeySequence("Space"), self, activated=tp.toggle_pause)

        # Esc — stop
        QShortcut(QKeySequence("Escape"), self, activated=tp.trigger_stop)

        # Ctrl+Enter — accept review
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=tp.trigger_next)

        # Ctrl+S — force commit
        QShortcut(QKeySequence.StandardKey.Save, self, activated=tp.force_commit)

    # ------------------------------------------------------------------
    # Resume dialog with hash verification
    # ------------------------------------------------------------------

    def _check_resume(self) -> None:
        session = self._db.load_session()
        if session is None:
            return

        book_id = session.get("book_id")
        if book_id is None:
            return

        book = self._db.load_book(book_id)
        if book is None:
            return

        source_path = book.source_path
        mode = session.get("mode", "auto")
        idx = session.get("current_paragraph_index", 0)
        total = sum(len(ch.paragraphs) for ch in book.chapters)

        # --- File existence check ---
        if not Path(source_path).exists():
            QMessageBox.warning(
                self,
                "Файл не найден",
                f"Файл книги не найден:\n{source_path}\n\n"
                "Невозможно продолжить перевод. Сессия будет очищена.",
            )
            self._db.clear_session()
            return

        # --- Hash comparison ---
        current_hash = compute_file_hash(source_path)
        hash_match = current_hash == book.file_hash

        if not hash_match:
            msg = QMessageBox(self)
            msg.setWindowTitle("Файл изменился")
            msg.setText(
                f"Файл книги изменился с момента последнего перевода."
            )
            msg.setInformativeText(
                f"Книга: {book.title}\n"
                f"Прогресс: {idx}/{total}\n\n"
                "Начать перевод заново или продолжить текущий (рискованно — "
                "нумерация абзацев могла измениться)?"
            )
            restart_btn = msg.addButton("Начать заново", QMessageBox.ButtonRole.YesRole)
            continue_btn = msg.addButton("Продолжить", QMessageBox.ButtonRole.NoRole)
            cancel_btn = msg.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            if msg.clickedButton() == restart_btn:
                self._reset_book(book_id)
                return
            elif msg.clickedButton() == cancel_btn:
                return
            # else continue_btn → fall through to resume
        else:
            # Hash matches — simple dialog
            msg = QMessageBox(self)
            msg.setWindowTitle("Восстановить сессию?")
            msg.setText(
                f"Обнаружен незавершённый перевод книги "
                f"«{book.title}»."
            )
            msg.setInformativeText(
                f"Переведено {idx} из {total} абзацев.\n\n"
                "Продолжить?"
            )
            resume_btn = msg.addButton("Продолжить", QMessageBox.ButtonRole.YesRole)
            restart_btn = msg.addButton("Начать заново", QMessageBox.ButtonRole.NoRole)
            cancel_btn = msg.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            if msg.clickedButton() == restart_btn:
                self._reset_book(book_id)
                return
            elif msg.clickedButton() == cancel_btn:
                return
            # else resume_btn → fall through

        # --- Resume translation ---
        self._glossary_panel.load_book(book)
        self._translation_panel.resume_session(
            book_id=book_id,
            mode=mode,
            translation_a_id=session.get("translation_a_id", 0),
            translation_b_id=session.get("translation_b_id"),
            current_index=idx,
        )
        self._translation_panel.set_book(book_id)
        self._tabs.setCurrentWidget(self._translation_panel)

    def _reset_book(self, book_id: int) -> None:
        """Delete book and session so user can start fresh."""
        self._db.clear_session()
        self._db.delete_book(book_id)
        self._glossary_panel.clear()
        self._translation_panel.set_book(None)
        self._tabs.setCurrentWidget(self._book_loader)
        self._status.showMessage("Сессия сброшена, загрузите книгу заново")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._db.close()
        event.accept()
