"""Translation panel — mode selection, progress, log, problem tracking."""

from datetime import datetime
from decimal import Decimal

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.config import ConfigManager
from core.glossary import GlossaryManager
from core.models import Paragraph, TranslationJob
from gui.worker import WorkerManager
from gui.widgets.paragraph_editor import ParagraphEditor
from state.database import Database
from translator.engine import TranslatorEngine


class TranslationPanel(QWidget):
    """Main translation control panel.

    Provides:
    - Mode selector (auto / interactive / hybrid)
    - Start / Pause / Resume / Stop controls
    - Progress bar(s)
    - Activity log
    - Problem (failed) paragraph list
    - Interactive review for manual editing
    """

    translation_started = pyqtSignal(int, int)   # translation_a_id, translation_b_id (0 if none)
    translation_finished = pyqtSignal()

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
        self._worker_mgr.interim_cost_a.connect(self._update_cost_a)
        self._worker_mgr.interim_cost_b.connect(self._update_cost_b)

        self._book_id: int | None = None
        self._review_paragraphs: dict[int, Paragraph] = {}

        self._build_ui()
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

        self._start_btn = QPushButton("▶ Начать")
        self._start_btn.clicked.connect(self._on_start)
        self._pause_btn = QPushButton("⏸ Пауза")
        self._pause_btn.clicked.connect(self._on_pause)
        self._resume_btn = QPushButton("▶ Продолжить")
        self._resume_btn.clicked.connect(self._on_resume)
        self._resume_btn.hide()
        self._stop_btn = QPushButton("⏹ Стоп")
        self._stop_btn.clicked.connect(self._on_stop)

        ctrl_row.addWidget(QLabel("Режим:"))
        ctrl_row.addWidget(self._mode_combo)
        ctrl_row.addSpacing(20)
        ctrl_row.addWidget(self._start_btn)
        ctrl_row.addWidget(self._pause_btn)
        ctrl_row.addWidget(self._resume_btn)
        ctrl_row.addWidget(self._stop_btn)
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

        # Bottom half: problem paragraphs + review editor
        bottom = QSplitter(Qt.Orientation.Horizontal)

        # -- Problem paragraphs ------------------------------------------
        prob_widget = QWidget()
        prob_layout = QVBoxLayout(prob_widget)
        prob_label = QLabel("Проблемные абзацы:")
        prob_label.setStyleSheet("font-weight: bold;")
        prob_layout.addWidget(prob_label)
        self._problem_list = QListWidget()
        prob_layout.addWidget(self._problem_list, 1)
        bottom.addWidget(prob_widget)

        # -- Review editor -----------------------------------------------
        self._editor = ParagraphEditor()
        self._editor.accepted.connect(self._on_review_accepted)
        self._editor.rejected.connect(self._on_review_rejected)
        self._editor.hide()
        bottom.addWidget(self._editor)

        splitter.addWidget(bottom)
        outer.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_book(self, book_id: int | None) -> None:
        self._book_id = book_id
        self._start_btn.setEnabled(book_id is not None)

    def resume_session(
        self,
        book_id: int,
        mode: str,
        translation_a_id: int,
        translation_b_id: int | None,
        current_index: int,
    ) -> None:
        self._book_id = book_id
        self._mode_combo.setCurrentText(mode)
        self.log(f"Сессия восстановлена (книга #{book_id}, шаг {current_index})")

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

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
        paragraphs_a = self._create_paragraphs_for_translation(
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

        self._worker_mgr.progress_changed.connect(self._on_progress_a)
        self._worker_mgr.worker_finished.connect(self._on_worker_finished)
        if compare:
            self._worker_mgr.progress_b_changed.connect(self._on_progress_b)

        # Setup progress
        self._progress_a_bar.setMaximum(len(paragraphs_a))
        self._progress_a_bar.setValue(0)

        # Clear state
        self._problem_list.clear()
        self._review_paragraphs.clear()
        self._editor.hide()

        # Start
        self._worker_mgr.start(
            book_id=self._book_id,
            translation_a_id=trans_a.id,
            job_a=job_a,
            paragraphs_a=paragraphs_a,
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

        # Save session
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
        )

    def _create_paragraphs_for_translation(
        self, book, translation_id: int
    ) -> list[Paragraph]:
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

    def _on_needs_review(
        self, idx: int, original: str, translation: str
    ) -> None:
        self._editor.set_content(original, translation)
        self._editor.show()

    def _on_review_accepted(self, edited_text: str) -> None:
        self._worker_mgr.submit_review(edited_text)
        self._editor.hide()

    def _on_review_rejected(self) -> None:
        self._worker_mgr.submit_review(None)
        self._editor.hide()

    # ------------------------------------------------------------------
    # Problem paragraphs
    # ------------------------------------------------------------------

    def _on_paragraph_failed(self, idx: int, error: str) -> None:
        item = QListWidgetItem(f"#{idx}: {error}")
        self._problem_list.addItem(item)
        self.log(f"Ошибка абзаца #{idx}: {error}")

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
