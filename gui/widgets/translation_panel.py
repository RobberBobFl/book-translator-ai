"""Translation panel — mode selection, progress, log, problem tracking."""

import asyncio
from datetime import datetime
from decimal import Decimal

from loguru import logger
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from exporters.markdown_exporter import check_translation_complete, export_to_markdown

from core.config import ConfigManager
from core.glossary import GlossaryManager
from core.models import Page, TranslationJob
from gui import i18n as gui_i18n
from gui.worker import TranslationWorker
from gui.widgets.page_editor import PageEditor
from state.database import Database
from translator.engine import TranslatorEngine


_LANGUAGE_OPTIONS = ["русский", "английский"]


class TranslationPanel(QWidget):
    """Main translation control panel.

    Provides:
    - Mode selector (auto / interactive / hybrid)
    - Start / Pause / Resume / Stop controls
    - Progress bar
    - Activity log
    - Problem (failed) page list
    - Interactive review for manual editing
    - Hybrid side panel with page list and status colors
    """

    translation_started = pyqtSignal(int)   # translation_id
    translation_finished = pyqtSignal()

    _COLOR_COMPLETED = QColor(200, 255, 200)
    _COLOR_FAILED = QColor(255, 200, 200)
    _COLOR_PENDING = QColor(255, 255, 200)
    _COLOR_REVIEW = QColor(200, 220, 255)

    def __init__(
        self,
        db: Database,
        config_manager: ConfigManager,
        engine: TranslatorEngine,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._cfg = config_manager
        self._engine = engine
        self._glossary_mgr = GlossaryManager(db)

        self._worker: TranslationWorker | None = None
        self._task: asyncio.Task | None = None

        self._book_id: int | None = None
        self._translation_id: int | None = None
        self._pages: list[Page] = []
        self._side_items: dict[int, QListWidgetItem] = {}
        self._current_review_idx: int | None = None

        self._build_ui()
        self._connect_editor_signals()
        self._init_lang_combo()
        self._update_model_label()
        self._set_running_state(False)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top half: controls + progress + log
        top = QWidget()
        top_layout = QVBoxLayout(top)

        # -- Controls row ------------------------------------------------
        ctrl_row = QHBoxLayout()

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["auto", "interactive", "hybrid"])
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)

        self._model_label = QLabel()
        self._model_label.setStyleSheet("font-weight: bold;")

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(_LANGUAGE_OPTIONS)
        self._lang_combo.setToolTip(gui_i18n.tr("tp.language_tooltip"))

        self._start_btn = QPushButton(gui_i18n.tr("tp.start"))
        self._start_btn.clicked.connect(self._on_start)
        self._pause_btn = QPushButton(gui_i18n.tr("tp.pause"))
        self._pause_btn.clicked.connect(self._on_pause)
        self._resume_btn = QPushButton(gui_i18n.tr("tp.resume"))
        self._resume_btn.clicked.connect(self._on_resume)
        self._resume_btn.hide()
        self._stop_btn = QPushButton(gui_i18n.tr("tp.stop"))
        self._stop_btn.clicked.connect(self._on_stop)
        self._export_btn = QPushButton(gui_i18n.tr("tp.export"))
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._export_btn.setEnabled(False)

        self._mode_lbl = QLabel(gui_i18n.tr("tp.mode"))
        ctrl_row.addWidget(self._mode_lbl)
        ctrl_row.addWidget(self._mode_combo)
        ctrl_row.addSpacing(10)
        ctrl_row.addWidget(self._model_label)
        ctrl_row.addSpacing(20)
        self._lang_lbl = QLabel(gui_i18n.tr("tp.language"))
        ctrl_row.addWidget(self._lang_lbl)
        ctrl_row.addWidget(self._lang_combo)
        ctrl_row.addSpacing(20)
        ctrl_row.addWidget(self._start_btn)
        ctrl_row.addWidget(self._pause_btn)
        ctrl_row.addWidget(self._resume_btn)
        ctrl_row.addWidget(self._stop_btn)
        ctrl_row.addSpacing(20)
        ctrl_row.addWidget(self._export_btn)
        ctrl_row.addStretch()
        top_layout.addLayout(ctrl_row)

        # -- Progress section --------------------------------------------
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat(gui_i18n.tr("tp.progress"))

        top_layout.addWidget(self._progress_bar)

        # -- Cost / tokens display ---------------------------------------
        cost_row = QHBoxLayout()
        self._cost_label = QLabel("0 tok · $0.00000")
        cost_row.addWidget(self._cost_label)
        cost_row.addStretch()
        top_layout.addLayout(cost_row)

        # -- Log ---------------------------------------------------------
        self._log_label = QLabel(gui_i18n.tr("tp.log_label"))
        self._log_label.setStyleSheet("font-weight: bold;")
        top_layout.addWidget(self._log_label)

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(500)
        top_layout.addWidget(self._log_text, 1)

        splitter.addWidget(top)

        # Bottom half: problem pages + editor + side panel
        bottom = QSplitter(Qt.Orientation.Horizontal)

        bottom_left = QWidget()
        bottom_left_layout = QVBoxLayout(bottom_left)

        # -- Problem pages -----------------------------------------------
        self._problem_label = QLabel(gui_i18n.tr("tp.problem_pages"))
        self._problem_label.setStyleSheet("font-weight: bold;")
        bottom_left_layout.addWidget(self._problem_label)

        self._problem_list = QListWidget()
        bottom_left_layout.addWidget(self._problem_list, 1)

        # -- Review editor -----------------------------------------------
        self._editor = PageEditor()
        self._editor.hide()
        bottom_left_layout.addWidget(self._editor)

        bottom.addWidget(bottom_left)

        # -- Hybrid side panel -------------------------------------------
        side_widget = QWidget()
        side_layout = QVBoxLayout(side_widget)
        side_label = QLabel("Страницы:")
        side_label.setStyleSheet("font-weight: bold;")
        side_layout.addWidget(side_label)

        self._side_list = QListWidget()
        self._side_list.itemClicked.connect(self._on_side_item_clicked)
        side_layout.addWidget(self._side_list, 1)

        bottom.addWidget(side_widget)
        splitter.addWidget(bottom)
        outer.addWidget(splitter, 1)

    def _connect_editor_signals(self) -> None:
        self._editor.accepted.connect(self._on_review_accepted)
        self._editor.rejected.connect(self._on_review_rejected)
        self._editor.back_requested.connect(self._on_review_back)
        self._editor.skip_requested.connect(self._on_review_skip)
        self._editor.rephrase_requested.connect(self._on_review_rephrase)
        self._editor.translate_requested.connect(self._on_review_translate)

    def _init_lang_combo(self) -> None:
        cfg = self._cfg.load_app_config()
        lang = cfg.get("target_language", "русский")
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentText(lang)
        self._lang_combo.blockSignals(False)
        self._lang_combo.currentTextChanged.connect(self._on_lang_changed)
        logger.info(f"Target language initialised: {lang}")

    def _on_lang_changed(self, lang: str) -> None:
        cfg = self._cfg.load_app_config()
        cfg["target_language"] = lang
        self._cfg.save_app_config(cfg)
        logger.info(f"Target language set to: {lang}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_book(self, book_id: int | None) -> None:
        self._book_id = book_id
        self._translation_id = None
        self._start_btn.setEnabled(book_id is not None)
        self._export_btn.setEnabled(book_id is not None)

    def refresh_models(self) -> None:
        """Called when providers change — updates the read-only model label."""
        self._update_model_label()

    def resume_session(
        self,
        book_id: int,
        mode: str,
        translation_id: int,
        current_index: int,
    ) -> None:
        self._book_id = book_id
        self._translation_id = translation_id
        self._mode_combo.setCurrentText(mode)
        self.log(gui_i18n.tr("tp.resume_session", book_id=book_id, current_index=current_index))

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def _on_export_clicked(self) -> None:
        if self._book_id is None or self._translation_id is None:
            QMessageBox.warning(
                self, gui_i18n.tr("tp.export"), gui_i18n.tr("tp.export_no_active")
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            gui_i18n.tr("tp.export_title"),
            "translation.md",
            gui_i18n.tr("tp.export_filter"),
        )
        if not file_path:
            return

        if not check_translation_complete(self._db, self._translation_id):
            reply = QMessageBox.question(
                self,
                gui_i18n.tr("tp.not_complete.title"),
                gui_i18n.tr("tp.not_complete.text"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            result = export_to_markdown(
                db=self._db,
                book_id=self._book_id,
                translation_id=self._translation_id,
                output_path=file_path,
                include_original=True,
            )
            QMessageBox.information(
                self, gui_i18n.tr("tp.export"), gui_i18n.tr("tp.export_done", result=result)
            )
            self.log(gui_i18n.tr("tp.export_done", result=result))
        except Exception as exc:
            QMessageBox.critical(
                self, gui_i18n.tr("tp.export_error.title"),
                gui_i18n.tr("tp.export_error.text", exc=exc),
            )
            self.log(gui_i18n.tr("tp.export_error.text", exc=exc))

    def _build_job(
        self,
        cfg: dict,
        mode: str,
        model_id: str | None = None,
    ) -> TranslationJob:
        return TranslationJob(
            model_id=model_id or cfg.get("last_model", ""),
            temperature=Decimal(str(cfg.get("temperature", 0.3))),
            top_p=Decimal(str(cfg.get("top_p", 0.9))),
            max_tokens=int(cfg.get("max_tokens", 4096)),
            style=cfg.get("style", "литературный"),
            mode=mode,
            target_language=self._lang_combo.currentText() or "русский",
        )

    def _on_start(self) -> None:
        if self._book_id is None:
            self.log(gui_i18n.tr("tp.err_book_not_selected"))
            return

        cfg = self._cfg.load_app_config()
        mode: str = self._mode_combo.currentText()

        book = self._db.load_book(self._book_id)
        if book is None:
            self.log(gui_i18n.tr("tp.err_book_not_found"))
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        job = self._build_job(cfg, mode)
        if not job.model_id:
            self.log(gui_i18n.tr("tp.err_model_not_selected"))
            return

        # --- empty book guard ---
        if not book.pages:
            self.log(gui_i18n.tr("tp.err_no_pages"))
            QMessageBox.warning(
                self,
                gui_i18n.tr("tp.no_pages.title"),
                gui_i18n.tr("tp.no_pages.text"),
            )
            return

        trans = self._db.create_translation(
            book_id=self._book_id,
            name=f"{mode} — {job.model_id} — {ts}",
            model_id=job.model_id,
            source_type="parallel",
            mode=mode,
        )
        self._translation_id = trans.id
        self._pages = self._create_pages_for_translation(book, trans.id)

        # Setup progress
        self._progress_bar.setMaximum(len(self._pages))
        self._progress_bar.setValue(0)

        # Clear state
        self._problem_list.clear()
        self._side_list.clear()
        self._side_items.clear()
        self._current_review_idx = None
        self._editor.hide()

        # Populate side panel with pending items
        for idx, p in enumerate(self._pages):
            item = self._make_side_item(idx, p)
            self._side_list.addItem(item)
            self._side_items[idx] = item

        # Create and start worker
        worker = TranslationWorker(
            db=self._db,
            engine=self._engine,
            book_id=self._book_id,
            translation_id=trans.id,
            job=job,
            pages=self._pages,
            current_index=0,
            glossary_mgr=self._glossary_mgr,
        )
        worker.progress_changed.connect(self._on_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.page_done.connect(self._on_page_done)
        worker.page_failed.connect(self._on_page_failed)
        worker.needs_review.connect(self._on_needs_review)
        worker.error_occurred.connect(self._on_error_occurred)
        worker.interim_cost.connect(self._update_cost)

        loop = asyncio.get_event_loop()
        self._task = loop.create_task(worker.run())
        self._worker = worker

        self._set_running_state(True)
        self.log(gui_i18n.tr("tp.started", pages=len(self._pages), mode=mode))
        self.log(gui_i18n.tr("tp.model_log", model=job.model_id))

        self.translation_started.emit(trans.id)

        self._db.save_session(
            book_id=self._book_id,
            mode=mode,
            translation_a_id=trans.id,
            current_page_index=0,
        )

    def _create_pages_for_translation(
        self, book, translation_id: int
    ) -> list[Page]:
        existing = self._db.get_pages(translation_id)
        if existing:
            return existing
        pages: list[Page] = []
        for p in book.pages:
            new_p = Page(
                translation_id=translation_id,
                book_id=self._book_id,
                chapter_title=p.chapter_title,
                page_number=p.page_number,
                original_text=p.original_text,
                model_id="",
                status="pending",
            )
            self._db.save_page(new_p)
            pages.append(new_p)
        return pages

    def _on_pause(self) -> None:
        if self._worker:
            self._worker.pause()
        self._pause_btn.hide()
        self._resume_btn.show()
        self.log(gui_i18n.tr("tp.paused"))

    def _on_resume(self) -> None:
        if self._worker:
            self._worker.resume()
        self._resume_btn.hide()
        self._pause_btn.show()
        self.log(gui_i18n.tr("tp.resumed"))

    def _on_stop(self) -> None:
        if self._worker:
            self._worker.stop()
        self.log(gui_i18n.tr("tp.stopped"))
        self._set_running_state(False)

    def _update_model_label(self) -> None:
        cfg = self._cfg.load_app_config()
        model = cfg.get("last_model", "").strip()
        self._model_label.setText(
            gui_i18n.tr("tp.model", model=model) if model
            else gui_i18n.tr("tp.model", model="—")
        )

    # ------------------------------------------------------------------
    # Live retranslation
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Re-apply all UI strings for the active language."""
        self._mode_lbl.setText(gui_i18n.tr("tp.mode"))
        self._lang_lbl.setText(gui_i18n.tr("tp.language"))
        self._start_btn.setText(gui_i18n.tr("tp.start"))
        self._pause_btn.setText(gui_i18n.tr("tp.pause"))
        self._resume_btn.setText(gui_i18n.tr("tp.resume"))
        self._stop_btn.setText(gui_i18n.tr("tp.stop"))
        self._export_btn.setText(gui_i18n.tr("tp.export"))
        self._progress_bar.setFormat(gui_i18n.tr("tp.progress"))
        self._log_label.setText(gui_i18n.tr("tp.log_label"))
        self._problem_label.setText(gui_i18n.tr("tp.problem_pages"))
        self._lang_combo.setToolTip(gui_i18n.tr("tp.language_tooltip"))
        self._update_model_label()

    # ------------------------------------------------------------------
    # Hotkey actions
    # ------------------------------------------------------------------

    def toggle_pause(self) -> None:
        if self._resume_btn.isVisible():
            self._on_resume()
        elif self._pause_btn.isVisible():
            self._on_pause()

    def trigger_stop(self) -> None:
        if self._stop_btn.isVisible():
            self._on_stop()

    def trigger_next(self) -> None:
        if self._editor.isVisible():
            self._on_review_accepted(self._editor.get_edited_text())

    def force_commit(self) -> None:
        try:
            self._db.conn.commit()
            self.log(gui_i18n.tr("tp.progress_saved"))
        except Exception as exc:
            self.log(gui_i18n.tr("tp.save_error", exc=exc))

    # ------------------------------------------------------------------
    # Worker signal handlers
    # ------------------------------------------------------------------

    def _on_progress(self, done: int, total: int) -> None:
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(done)

    def _on_worker_finished(self) -> None:
        self.log(gui_i18n.tr("tp.finished"))
        self._set_running_state(False)
        self.translation_finished.emit()

    def _on_error_occurred(self, message: str) -> None:
        QMessageBox.critical(
            self, gui_i18n.tr("tp.critical_title"),
            gui_i18n.tr("tp.critical", message=message),
        )
        self.log(f"Критическая ошибка: {message}")
        self._set_running_state(False)

    def _on_needs_review(
        self, idx: int, original: str, translation: str
    ) -> None:
        self._current_review_idx = idx
        self._editor.set_content(original, translation, idx)
        self._editor.show()

    def _on_page_done(self, idx: int, page_id: int) -> None:
        item = self._side_items.get(idx)
        if item is not None:
            item.setBackground(self._COLOR_COMPLETED)

    def _on_page_failed(self, idx: int, error: str) -> None:
        item = QListWidgetItem(f"#стр.{idx}: {error}")
        self._problem_list.addItem(item)
        self.log(gui_i18n.tr("tp.page_failed", idx=idx, error=error))
        side = self._side_items.get(idx)
        if side is not None:
            side.setBackground(self._COLOR_FAILED)

    # ------------------------------------------------------------------
    # Editor signal handlers
    # ------------------------------------------------------------------

    def _on_review_accepted(self, edited_text: str) -> None:
        if self._worker:
            self._worker.submit_review(edited_text)
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_rejected(self) -> None:
        if self._worker:
            self._worker.submit_review(None)
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_back(self) -> None:
        if self._worker:
            self._worker.go_back()
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_skip(self) -> None:
        if self._worker:
            self._worker.submit_review(None)
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_rephrase(self) -> None:
        if self._worker:
            self._worker.rephrase()
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_translate(self) -> None:
        idx = self._editor.current_review_idx
        if idx is not None and idx >= 0 and idx < len(self._pages):
            if self._worker:
                self._worker.translate_page(idx)
        self._editor.hide()
        self._current_review_idx = None

    # ------------------------------------------------------------------
    # Side panel
    # ------------------------------------------------------------------

    def _on_side_item_clicked(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        if idx < 0 or idx >= len(self._pages):
            return
        page = self._pages[idx]
        self._editor.set_content(page.original_text, page.translated_text or "", idx)
        self._current_review_idx = idx
        self._editor.show()

    def _make_side_item(self, idx: int, page: Page) -> QListWidgetItem:
        chapter = page.chapter_title or "?"
        text = page.original_text[:60].replace("\n", " ")
        label = f"§{idx} [{chapter}/стр.{page.page_number}] {text}"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, idx)
        if page.status == "completed" and page.translated_text:
            item.setBackground(self._COLOR_COMPLETED)
        elif page.status == "failed":
            item.setBackground(self._COLOR_FAILED)
        return item

    # ------------------------------------------------------------------
    # Mode change
    # ------------------------------------------------------------------

    def _on_mode_changed(self, mode: str) -> None:
        if mode in ("interactive", "hybrid"):
            self._editor.show()
        else:
            self._editor.hide()

    # ------------------------------------------------------------------
    # UI state
    # ------------------------------------------------------------------

    def _set_running_state(self, running: bool) -> None:
        self._start_btn.setEnabled(not running and self._book_id is not None)
        self._mode_combo.setEnabled(not running)
        self._pause_btn.setVisible(running)
        self._resume_btn.setVisible(False)
        self._stop_btn.setVisible(running)
        self._export_btn.setEnabled(not running and self._book_id is not None)

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.appendPlainText(f"[{ts}] {message}")

    # ------------------------------------------------------------------
    # Cost update
    # ------------------------------------------------------------------

    def _update_cost(self, tokens_in: int, tokens_out: int, cost: float) -> None:
        self._cost_label.setText(f"{tokens_in + tokens_out} tok · ${cost:.5f}")
