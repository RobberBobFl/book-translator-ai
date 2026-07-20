"""Main application window — tabbed assembly, menu, resume dialog."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from core.config import ConfigManager
from gui import i18n as gui_i18n
from gui import theme as gui_theme
from gui.widgets.book_loader import BookLoaderWidget
from gui.widgets.settings_panel import SettingsPanel
from gui.widgets.translation_panel import TranslationPanel
from state.database import Database
from translator.engine import TranslatorEngine
from utils.hash_utils import compute_file_hash

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

        # Apply the UI language as early as possible so every widget built
        # below picks up the correct strings.
        gui_i18n.set_language(self._cfg.load_app_config().get("ui_language", "auto"))

        self._db = Database(_DB_PATH)
        self._db.connect()
        self._db.initialize()
        self._engine = TranslatorEngine(self._cfg)

        # -- Panels ------------------------------------------------------
        self._book_loader = BookLoaderWidget(self._db, self._cfg)
        self._translation_panel = TranslationPanel(self._db, self._cfg, self._engine)
        self._settings_panel = SettingsPanel(self._cfg)

        # -- Tab widget --------------------------------------------------
        self._tabs = QTabWidget()
        self._tabs.addTab(self._book_loader, gui_i18n.tr("tab.book"))
        self._tabs.addTab(self._translation_panel, gui_i18n.tr("tab.translate"))
        self._tabs.addTab(self._settings_panel, gui_i18n.tr("tab.settings"))
        self.setCentralWidget(self._tabs)

        # -- Menu bar ----------------------------------------------------
        self._build_menu()

        # -- Status bar --------------------------------------------------
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(gui_i18n.tr("status.ready"))

        # -- Hotkeys -----------------------------------------------------
        self._build_hotkeys()

        # -- Top bar (language + theme selectors, top-right) --------------
        self._build_topbar()
        gui_theme.apply_theme(self._cfg.load_app_config().get("theme", "auto"))

        # -- Signal wiring -----------------------------------------------
        self._connect_signals()

        # -- Resume ------------------------------------------------------
        self._check_resume()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        # File menu
        file_menu = self.menuBar().addMenu(gui_i18n.tr("menu.file"))

        open_action = QAction(gui_i18n.tr("menu.open"), self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._on_menu_open)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        quit_action = QAction(gui_i18n.tr("menu.quit"), self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Help menu
        help_menu = self.menuBar().addMenu(gui_i18n.tr("menu.help"))

        about_action = QAction(gui_i18n.tr("menu.about"), self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    # ------------------------------------------------------------------
    # Top bar (language + theme selectors)
    # ------------------------------------------------------------------

    def _build_topbar(self) -> None:
        """Add language + theme selectors to the top-right of the menu bar."""
        self._topbar = QWidget()
        layout = QHBoxLayout(self._topbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        cfg = self._cfg.load_app_config()

        # -- Language selector --
        self._lang_combo = QComboBox()
        self._lang_combo.addItems(gui_i18n.LANGUAGE_LABELS)
        self._lang_combo.setToolTip(gui_i18n.tr("topbar.language_tooltip"))
        self._lang_combo.setMinimumWidth(110)
        self._lang_combo.setMaximumWidth(140)
        self._lang_combo.setCurrentText(
            gui_i18n.language_label(cfg.get("ui_language", "auto"))
        )
        self._lang_combo.currentTextChanged.connect(self._on_language_changed)
        layout.addWidget(self._lang_combo)

        # -- Theme selector --
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(
            [
                gui_theme.theme_label(gui_theme.THEME_AUTO),
                gui_theme.theme_label(gui_theme.THEME_LIGHT),
                gui_theme.theme_label(gui_theme.THEME_DARK),
            ]
        )
        self._theme_combo.setToolTip(gui_i18n.tr("topbar.theme_tooltip"))
        self._theme_combo.setMinimumWidth(120)
        self._theme_combo.setMaximumWidth(150)
        self._theme_combo.setCurrentText(
            gui_theme.theme_label(cfg.get("theme", "auto"))
        )
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        layout.addWidget(self._theme_combo)

        self.menuBar().setCornerWidget(self._topbar, Qt.Corner.TopRightCorner)

    def _on_theme_changed(self, label: str) -> None:
        theme = gui_theme.label_to_theme(label)
        cfg = self._cfg.load_app_config()
        cfg["theme"] = theme
        self._cfg.save_app_config(cfg)
        gui_theme.apply_theme(theme)
        self._status.showMessage(gui_i18n.tr("topbar.theme_tooltip"))

    def _on_language_changed(self, label: str) -> None:
        lang = gui_i18n.label_to_language(label)
        cfg = self._cfg.load_app_config()
        cfg["ui_language"] = lang
        self._cfg.save_app_config(cfg)
        gui_i18n.set_language(lang)
        self.retranslate_ui()

    # ------------------------------------------------------------------
    # Retranslation (live language switch)
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Re-apply all UI strings for the active language."""
        self.menuBar().clear()
        self._build_menu()
        self.menuBar().setCornerWidget(self._topbar, Qt.Corner.TopRightCorner)

        self._tabs.setTabText(0, gui_i18n.tr("tab.book"))
        self._tabs.setTabText(1, gui_i18n.tr("tab.translate"))
        self._tabs.setTabText(2, gui_i18n.tr("tab.settings"))

        self._status.showMessage(gui_i18n.tr("status.ready"))

        self._book_loader.retranslate_ui()
        self._translation_panel.retranslate_ui()
        self._settings_panel.retranslate_ui()

        # Keep the top-bar combo tooltips in sync.
        self._lang_combo.setToolTip(gui_i18n.tr("topbar.language_tooltip"))
        self._theme_combo.setToolTip(gui_i18n.tr("topbar.theme_tooltip"))

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._book_loader.book_loaded.connect(self._on_book_loaded)
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
        self._translation_panel.set_book(book_id)
        self._tabs.setCurrentWidget(self._translation_panel)
        self._status.showMessage(
            gui_i18n.tr(
                "status.loaded",
                title=book.title,
                chapters=len(book.chapters),
                pages=len(book.pages),
            )
        )

    def _on_translation_finished(self) -> None:
        self._status.showMessage(gui_i18n.tr("status.translation_finished"))

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _on_menu_open(self) -> None:
        self._book_loader._on_open_clicked()

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            gui_i18n.tr("app.about_title"),
            gui_i18n.tr("app.about_text"),
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
        idx = session.get("current_page_index", 0)
        total = len(book.pages) if book.pages else 0

        # --- File existence check ---
        if not Path(source_path).exists():
            QMessageBox.warning(
                self,
                gui_i18n.tr("dlg.file_not_found.title"),
                gui_i18n.tr("dlg.file_not_found.text", path=source_path),
            )
            self._db.clear_session()
            return

        # --- Hash comparison ---
        current_hash = compute_file_hash(source_path)
        hash_match = current_hash == book.file_hash

        if not hash_match:
            msg = QMessageBox(self)
            msg.setWindowTitle(gui_i18n.tr("dlg.file_changed.title"))
            msg.setText(gui_i18n.tr("dlg.file_changed.text"))
            msg.setInformativeText(
                gui_i18n.tr(
                    "dlg.file_changed.info",
                    title=book.title,
                    idx=idx,
                    total=total,
                )
            )
            restart_btn = msg.addButton(
                gui_i18n.tr("btn.restart"), QMessageBox.ButtonRole.YesRole
            )
            msg.addButton(
                gui_i18n.tr("btn.continue"), QMessageBox.ButtonRole.NoRole
            )
            cancel_btn = msg.addButton(
                gui_i18n.tr("btn.cancel"), QMessageBox.ButtonRole.RejectRole
            )
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
            msg.setWindowTitle(gui_i18n.tr("dlg.resume.title"))
            msg.setText(
                gui_i18n.tr("dlg.resume.text", title=book.title)
            )
            msg.setInformativeText(
                gui_i18n.tr("dlg.resume.info", idx=idx, total=total)
            )
            msg.addButton(
                gui_i18n.tr("btn.continue"), QMessageBox.ButtonRole.YesRole
            )
            restart_btn = msg.addButton(
                gui_i18n.tr("btn.restart"), QMessageBox.ButtonRole.NoRole
            )
            cancel_btn = msg.addButton(
                gui_i18n.tr("btn.cancel"), QMessageBox.ButtonRole.RejectRole
            )
            msg.exec()

            if msg.clickedButton() == restart_btn:
                self._reset_book(book_id)
                return
            elif msg.clickedButton() == cancel_btn:
                return
            # else resume_btn → fall through

        # --- Resume translation ---
        self._translation_panel.resume_session(
            book_id=book_id,
            mode=mode,
            translation_id=session.get("translation_a_id", 0),
            current_index=idx,
        )
        self._translation_panel.set_book(book_id)
        self._tabs.setCurrentWidget(self._translation_panel)

    def _reset_book(self, book_id: int) -> None:
        """Delete book and session so user can start fresh."""
        self._db.clear_session()
        self._db.delete_book(book_id)
        self._translation_panel.set_book(None)
        self._tabs.setCurrentWidget(self._book_loader)
        self._status.showMessage(gui_i18n.tr("status.session_reset"))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._db.close()
        event.accept()
