"""Translation panel — mode selection, progress, log, problem tracking."""

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
from core.models import Paragraph, TranslationJob
from gui.worker import WorkerManager
from gui.widgets.paragraph_editor import ParagraphEditor
from state.database import Database
from translator.engine import TranslatorEngine


_LANGUAGE_OPTIONS = ["русский", "английский"]


class TranslationPanel(QWidget):
    """Main translation control panel.

    Provides:
    - Mode selector (auto / interactive / hybrid)
    - Start / Pause / Resume / Stop controls
    - Progress bar(s)
    - Activity log
    - Problem (failed) paragraph list
    - Interactive review for manual editing
    - Hybrid side panel with paragraph list and status colors
    """

    translation_started = pyqtSignal(int, int)   # translation_a_id, translation_b_id (0 if none)
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
        self._glossary_mgr = GlossaryManager(db)

        self._worker_mgr = WorkerManager(db, engine)
        self._worker_mgr.set_glossary_manager(self._glossary_mgr)
        self._worker_mgr.all_finished.connect(self._on_all_finished)
        self._worker_mgr.needs_review.connect(self._on_needs_review)
        self._worker_mgr.paragraph_failed.connect(self._on_paragraph_failed)
        self._worker_mgr.error_occurred.connect(self._on_error_occurred)
        self._worker_mgr.interim_cost_a.connect(self._update_cost_a)
        self._worker_mgr.interim_cost_b.connect(self._update_cost_b)

        self._book_id: int | None = None
        self._translation_a_id: int | None = None
        self._paragraphs_a: list[Paragraph] = []
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

        self._model_label = QLabel("Модель: —")
        self._model_label.setStyleSheet("font-weight: bold;")

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(_LANGUAGE_OPTIONS)
        self._lang_combo.setToolTip("Язык, на который выполняется перевод")

        self._start_btn = QPushButton("▶ Начать")
        self._start_btn.clicked.connect(self._on_start)
        self._pause_btn = QPushButton("⏸ Пауза")
        self._pause_btn.clicked.connect(self._on_pause)
        self._resume_btn = QPushButton("▶ Продолжить")
        self._resume_btn.clicked.connect(self._on_resume)
        self._resume_btn.hide()
        self._stop_btn = QPushButton("⏹ Стоп")
        self._stop_btn.clicked.connect(self._on_stop)
        self._export_btn = QPushButton("💾 Сохранить как MD")
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._export_btn.setEnabled(False)

        ctrl_row.addWidget(QLabel("Режим:"))
        ctrl_row.addWidget(self._mode_combo)
        ctrl_row.addSpacing(10)
        ctrl_row.addWidget(self._model_label)
        ctrl_row.addSpacing(20)
        ctrl_row.addWidget(QLabel("Язык:"))
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
        self._progress_a_bar = QProgressBar()
        self._progress_a_bar.setTextVisible(True)
        self._progress_a_bar.setFormat("Model A: %v / %m")
        self._progress_b_bar = QProgressBar()
        self._progress_b_bar.setTextVisible(True)
        self._progress_b_bar.setFormat("Model B: %v / %m")
        self._progress_b_bar.hide()

        top_layout.addWidget(self._progress_a_bar)
        top_layout.addWidget(self._progress_b_bar)

        # -- Cost / tokens display ---------------------------------------
        cost_row = QHBoxLayout()
        self._cost_a_label = QLabel("A: 0 tok · $0.00000")
        self._cost_b_label = QLabel("B: 0 tok · $0.00000")
        self._cost_b_label.hide()
        cost_row.addWidget(self._cost_a_label)
        cost_row.addWidget(self._cost_b_label)
        cost_row.addStretch()
        top_layout.addLayout(cost_row)

        # -- Log ---------------------------------------------------------
        log_label = QLabel("Лог перевода:")
        log_label.setStyleSheet("font-weight: bold;")
        top_layout.addWidget(log_label)

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(500)
        top_layout.addWidget(self._log_text, 1)

        splitter.addWidget(top)

        # Bottom half: problem paragraphs + editor + side panel
        bottom = QSplitter(Qt.Orientation.Horizontal)

        bottom_left = QWidget()
        bottom_left_layout = QVBoxLayout(bottom_left)

        # -- Problem paragraphs ------------------------------------------
        prob_label = QLabel("Проблемные абзацы:")
        prob_label.setStyleSheet("font-weight: bold;")
        bottom_left_layout.addWidget(prob_label)

        self._problem_list = QListWidget()
        bottom_left_layout.addWidget(self._problem_list, 1)

        # -- Review editor -----------------------------------------------
        self._editor = ParagraphEditor()
        self._editor.hide()
        bottom_left_layout.addWidget(self._editor)

        bottom.addWidget(bottom_left)

        # -- Hybrid side panel -------------------------------------------
        side_widget = QWidget()
        side_layout = QVBoxLayout(side_widget)
        side_label = QLabel("Абзацы:")
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
        self._translation_a_id = None
        self._start_btn.setEnabled(book_id is not None)
        self._export_btn.setEnabled(book_id is not None)

    def refresh_models(self) -> None:
        """Called when providers change — updates the read-only model label."""
        self._update_model_label()

    def resume_session(
        self,
        book_id: int,
        mode: str,
        translation_a_id: int,
        translation_b_id: int | None,
        current_index: int,
    ) -> None:
        self._book_id = book_id
        self._translation_a_id = translation_a_id
        self._mode_combo.setCurrentText(mode)
        self.log(f"Сессия восстановлена (книга #{book_id}, шаг {current_index})")

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def _on_export_clicked(self) -> None:
        if self._book_id is None or self._translation_a_id is None:
            QMessageBox.warning(self, "Экспорт", "Нет активного перевода для экспорта.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить перевод как Markdown",
            "translation.md",
            "Markdown files (*.md);;All files (*)",
        )
        if not file_path:
            return

        if not check_translation_complete(self._db, self._translation_a_id):
            reply = QMessageBox.question(
                self,
                "Перевод не завершён",
                "Перевод ещё не завершён. Экспортировать как есть?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            result = export_to_markdown(
                db=self._db,
                book_id=self._book_id,
                translation_id=self._translation_a_id,
                output_path=file_path,
                include_original=True,
            )
            QMessageBox.information(self, "Экспорт", f"Перевод сохранён:\n{result}")
            self.log(f"Экспорт завершён: {result}")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка экспорта", f"Не удалось сохранить файл:\n{exc}")
            self.log(f"Ошибка экспорта: {exc}")

    def _on_start(self) -> None:
        if self._book_id is None:
            self.log("Ошибка: книга не выбрана")
            return

        cfg = self._cfg.load_app_config()
        mode: str = self._mode_combo.currentText()

        book = self._db.load_book(self._book_id)
        if book is None:
            self.log("Ошибка: книга не найдена")
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # --- worker A setup ---
        job_a = self._build_job(cfg, mode)
        if not job_a.model_id:
            self.log("Ошибка: Model A не выбрана")
            return

        trans_a = self._db.create_translation(
            book_id=self._book_id,
            name=f"{mode} — {job_a.model_id} — {ts}",
            model_id=job_a.model_id,
            source_type="parallel",
            mode=mode,
        )
        self._translation_a_id = trans_a.id
        self._paragraphs_a = self._create_paragraphs_for_translation(
            book, trans_a.id
        )

        # --- worker B setup (comparison) ---
        compare = cfg.get("comparison_enabled", False)
        translation_b_id = None
        paragraphs_b = None
        job_b = None

        if compare:
            model_b = cfg.get("last_model_b", "")
            if model_b:
                job_b = self._build_job(cfg, mode, model_b)
                trans_b = self._db.create_translation(
                    book_id=self._book_id,
                    name=f"{mode} — {model_b} — {ts}",
                    model_id=model_b,
                    source_type="parallel",
                    mode=mode,
                )
                translation_b_id = trans_b.id
                paragraphs_b = self._create_paragraphs_for_translation(
                    book, trans_b.id
                )
                self._progress_b_bar.setMaximum(len(paragraphs_b))
                self._progress_b_bar.setValue(0)
                self._progress_b_bar.show()
                self._cost_b_label.show()
            else:
                compare = False

        # clear prior signal connections
        try:
            self._worker_mgr.progress_changed.disconnect()
        except TypeError:
            pass
        try:
            self._worker_mgr.progress_b_changed.disconnect()
        except TypeError:
            pass
        try:
            self._worker_mgr.worker_finished.disconnect()
        except TypeError:
            pass
        try:
            self._worker_mgr.paragraph_done.disconnect()
        except TypeError:
            pass

        self._worker_mgr.progress_changed.connect(self._on_progress_a)
        self._worker_mgr.worker_finished.connect(self._on_worker_finished)
        self._worker_mgr.paragraph_done.connect(self._on_paragraph_done)
        if compare:
            self._worker_mgr.progress_b_changed.connect(self._on_progress_b)

        # Setup progress
        self._progress_a_bar.setMaximum(len(self._paragraphs_a))
        self._progress_a_bar.setValue(0)

        # Clear state
        self._problem_list.clear()
        self._side_list.clear()
        self._side_items.clear()
        self._current_review_idx = None
        self._editor.hide()

        # Populate side panel with pending items
        for idx, p in enumerate(self._paragraphs_a):
            item = self._make_side_item(idx, p)
            self._side_list.addItem(item)
            self._side_items[idx] = item

        # Start
        self._worker_mgr.start(
            book_id=self._book_id,
            translation_a_id=trans_a.id,
            job_a=job_a,
            paragraphs_a=self._paragraphs_a,
            start_index_a=0,
            translation_b_id=translation_b_id,
            job_b=job_b,
            paragraphs_b=paragraphs_b,
            start_index_b=0,
        )

        self._set_running_state(True)
        self.log(f"Запущен перевод (режим: {mode})")
        if compare and job_b:
            self.log(f" Model A: {job_a.model_id} | Model B: {job_b.model_id}")
        else:
            self.log(f" Model: {job_a.model_id}")

        self.translation_started.emit(trans_a.id, translation_b_id or 0)

        self._db.save_session(
            book_id=self._book_id,
            mode=mode,
            translation_a_id=trans_a.id,
            translation_b_id=translation_b_id,
            current_index=0,
        )

    def _build_job(
        self,
        cfg: dict,
        mode: str,
        model_id: str | None = None,
    ) -> TranslationJob:
        return TranslationJob(
            model_id=model_id or cfg.get("last_model_a", ""),
            temperature=Decimal(str(cfg.get("temperature", 0.3))),
            top_p=Decimal(str(cfg.get("top_p", 0.9))),
            max_tokens=int(cfg.get("max_tokens", 4096)),
            style=cfg.get("style", "литературный"),
            mode=mode,
            target_language=self._lang_combo.currentText() or "русский",
        )

    def _create_paragraphs_for_translation(
        self, book, translation_id: int
    ) -> list[Paragraph]:
        existing = self._db.get_paragraphs(translation_id)
        if existing:
            return existing
        paragraphs: list[Paragraph] = []
        for ch in book.chapters:
            for p in ch.paragraphs:
                new_p = Paragraph(
                    translation_id=translation_id,
                    book_id=self._book_id,
                    chapter_title=p.chapter_title,
                    paragraph_index=p.paragraph_index,
                    original_text=p.original_text,
                    model_id="",
                    status="pending",
                )
                self._db.save_paragraph(new_p)
                paragraphs.append(new_p)
        return paragraphs

    def _on_pause(self) -> None:
        self._worker_mgr.pause()
        self._pause_btn.hide()
        self._resume_btn.show()
        self.log("Перевод приостановлен")

    def _on_resume(self) -> None:
        self._worker_mgr.resume()
        self._resume_btn.hide()
        self._pause_btn.show()
        self.log("Перевод продолжен")

    def _on_stop(self) -> None:
        self._worker_mgr.stop()
        self.log("Перевод остановлен пользователем")
        self._set_running_state(False)

    def _update_model_label(self) -> None:
        cfg = self._cfg.load_app_config()
        model = cfg.get("last_model_a", "").strip()
        self._model_label.setText(f"Модель: {model}" if model else "Модель: —")

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
            self.log("Прогресс сохранён")
        except Exception as exc:
            self.log(f"Ошибка сохранения: {exc}")

    # ------------------------------------------------------------------
    # Worker signal handlers
    # ------------------------------------------------------------------

    def _on_progress_a(self, done: int, total: int) -> None:
        self._progress_a_bar.setMaximum(total)
        self._progress_a_bar.setValue(done)

    def _on_progress_b(self, done: int, total: int) -> None:
        self._progress_b_bar.setMaximum(total)
        self._progress_b_bar.setValue(done)

    def _on_worker_finished(self, model_id: str) -> None:
        self.log(f"Worker завершён: {model_id}")

    def _on_all_finished(self) -> None:
        self.log("Перевод завершён")
        self._set_running_state(False)
        self.translation_finished.emit()

    def _on_error_occurred(self, message: str) -> None:
        QMessageBox.critical(self, "Критическая ошибка", f"Перевод остановлен:\n{message}")
        self.log(f"Критическая ошибка: {message}")
        self._set_running_state(False)

    def _on_needs_review(
        self, idx: int, original: str, translation: str
    ) -> None:
        self._current_review_idx = idx
        self._editor.set_content(original, translation, idx)
        self._editor.show()

    def _on_paragraph_done(self, idx: int, paragraph_id: int) -> None:
        # Update side panel item color
        item = self._side_items.get(idx)
        if item is not None:
            item.setBackground(self._COLOR_COMPLETED)

    def _on_paragraph_failed(self, idx: int, error: str) -> None:
        item = QListWidgetItem(f"#{idx}: {error}")
        self._problem_list.addItem(item)
        self.log(f"Ошибка абзаца #{idx}: {error}")
        # Update side panel item color
        side = self._side_items.get(idx)
        if side is not None:
            side.setBackground(self._COLOR_FAILED)

    # ------------------------------------------------------------------
    # Editor signal handlers
    # ------------------------------------------------------------------

    def _on_review_accepted(self, edited_text: str) -> None:
        self._worker_mgr.submit_review(edited_text)
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_rejected(self) -> None:
        self._worker_mgr.submit_review(None)
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_back(self) -> None:
        self._worker_mgr.go_back()
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_skip(self) -> None:
        self._worker_mgr.submit_review(None)
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_rephrase(self) -> None:
        self._worker_mgr.rephrase()
        self._editor.hide()
        self._current_review_idx = None

    def _on_review_translate(self) -> None:
        idx = self._editor.current_review_idx if hasattr(self._editor, 'current_review_idx') else None
        if idx is not None and idx >= 0 and idx < len(self._paragraphs_a):
            self._worker_mgr.translate_paragraph(idx)
        self._editor.hide()
        self._current_review_idx = None

    # ------------------------------------------------------------------
    # Side panel
    # ------------------------------------------------------------------

    def _on_side_item_clicked(self, item: QListWidgetItem) -> None:
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        if idx < 0 or idx >= len(self._paragraphs_a):
            return
        para = self._paragraphs_a[idx]
        if para.translated_text:
            self._editor.set_content(para.original_text, para.translated_text, idx)
        else:
            self._editor.set_content(para.original_text, "", idx)
        self._current_review_idx = idx
        self._editor.show()

    def _make_side_item(self, idx: int, para: Paragraph) -> QListWidgetItem:
        chapter = para.chapter_title or "?"
        text = para.original_text[:60].replace("\n", " ")
        label = f"§{idx} [{chapter}] {text}"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, idx)
        if para.status == "completed" and para.translated_text:
            item.setBackground(self._COLOR_COMPLETED)
        elif para.status == "failed":
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

    def _update_cost_a(self, tokens_in: int, tokens_out: int, cost: float) -> None:
        self._cost_a_label.setText(f"A: {tokens_in + tokens_out} tok · ${cost:.5f}")

    def _update_cost_b(self, tokens_in: int, tokens_out: int, cost: float) -> None:
        self._cost_b_label.setText(f"B: {tokens_in + tokens_out} tok · ${cost:.5f}")
