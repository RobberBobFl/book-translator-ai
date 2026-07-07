"""Async translation worker with auto/interactive/hybrid modes, pause/resume."""

import asyncio
from decimal import Decimal

from loguru import logger
from PyQt6.QtCore import QObject, pyqtSignal

from core.glossary import GlossaryManager
from core.models import Page, TranslationJob
from state.database import Database
from translator.context_builder import build_context
from translator.engine import (
    CriticalTranslationError,
    TranslationError,
    TranslatorEngine,
)
from translator.prompt_builder import build_messages
from utils.lang_utils import detect_source_language


class TranslationWorker(QObject):
    """Async worker that translates pages for one model.

    Run via::

        task = asyncio.create_task(worker.run())
    """

    # (completed_count, total_count)
    progress_changed = pyqtSignal(int, int)
    # (page_index, page_id) — saved to DB
    page_done = pyqtSignal(int, int)
    # (page_index, error_message)
    page_failed = pyqtSignal(int, str)
    # total_tokens_in, total_tokens_out, total_cost_usd
    interim_cost = pyqtSignal(int, int, float)
    finished = pyqtSignal()
    # (page_index, original_text, model_translation)
    needs_review = pyqtSignal(int, str, str)
    # Critical error that stopped translation
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        db: Database,
        engine: TranslatorEngine,
        book_id: int,
        translation_id: int,
        job: TranslationJob,
        pages: list[Page],
        current_index: int = 0,
        glossary_mgr: GlossaryManager | None = None,
    ) -> None:
        super().__init__()
        self._db = db
        self._engine = engine
        self._book_id = book_id
        self._translation_id = translation_id
        self._job = job
        self._pages = pages
        self._current_index = current_index
        self._glossary_mgr = glossary_mgr

        self._stop_requested = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused by default

        self._review_future: asyncio.Future[str] | None = None
        self._rephrase_requested = False
        self._back_requested = False

        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._total_cost = Decimal("0")

        self._source_language: str | None = None  # lazy cache
        logger.debug(f"TranslationWorker init: model={job.model_id}, target_language={job.target_language}, mode={job.mode}, pages={len(pages)}")

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def stop(self) -> None:
        self._stop_requested = True
        self._pause_event.set()

    def submit_review(self, edited_text: str | None) -> None:
        if self._review_future is not None and not self._review_future.done():
            self._review_future.set_result(edited_text)

    def go_back(self) -> None:
        self._back_requested = True
        self.submit_review(None)

    def rephrase(self) -> None:
        self._rephrase_requested = True
        if self._review_future is not None and not self._review_future.done():
            self._review_future.set_result(None)

    async def translate_page(self, idx: int) -> None:
        if not (0 <= idx < len(self._pages)):
            return
        page = self._pages[idx]

        if self._source_language is None:
            text = " ".join(p.original_text for p in self._pages)
            self._source_language = detect_source_language(text)

        glossary_block = ""
        if self._glossary_mgr is not None:
            try:
                glossary_block = self._glossary_mgr.format_for_prompt(self._book_id)
            except Exception:
                logger.exception("Failed to build glossary block")

        context = build_context(self._pages, idx, n=2)

        messages = build_messages(
            original_text=page.original_text,
            context_block=context,
            glossary_block=glossary_block,
            style=self._job.style,
            source_language=self._source_language,
            target_language=self._job.target_language,
        )
        logger.debug(
            f"translate_page[{idx}] system prompt: {messages[0]['content'][:200]}"
        )

        result = await self._engine.translate(
            messages=messages,
            model_id=self._job.model_id,
            temperature=float(self._job.temperature),
            top_p=float(self._job.top_p),
            max_tokens=self._job.max_tokens,
        )

        page.translated_text = result.text
        page.tokens_in = result.tokens_in
        page.tokens_out = result.tokens_out
        page.cost_usd = result.cost_usd
        page.model_id = result.model_id
        page.retry_count = 0
        page.error_message = None

        page.status = "completed"
        self._db.save_page(page)
        logger.info(f"Page {idx} translated: {result.tokens_in} in / {result.tokens_out} out / ${result.cost_usd}")

        self._total_tokens_in += result.tokens_in
        self._total_tokens_out += result.tokens_out
        self._total_cost += result.cost_usd

        self.page_done.emit(idx, page.id)
        self.progress_changed.emit(idx + 1, len(self._pages))
        self.interim_cost.emit(self._total_tokens_in, self._total_tokens_out, self._total_cost)

    # ------------------------------------------------------------------
    # Main loop (while-loop for back navigation)
    # ------------------------------------------------------------------

    async def run(self) -> None:
        total = len(self._pages)
        logger.info(f"Starting translation: {total} pages, model={self._job.model_id}, target_language={self._job.target_language}")

        while 0 <= self._current_index < total:
            if self._stop_requested:
                break

            await self._pause_event.wait()
            if self._stop_requested:
                break

            idx = self._current_index
            page = self._pages[idx]

            try:
                await self._translate_page(page, idx, total)
            except asyncio.CancelledError:
                break
            except CriticalTranslationError as exc:
                logger.error(f"Critical error on page {idx}: {exc}")
                self._stop_requested = True
                self.error_occurred.emit(str(exc))
                break
            except TranslationError as exc:
                logger.warning(f"Page {idx} failed after retries: {exc}")
                page.status = "failed"
                page.error_message = str(exc)
                self._db.save_page(page)
                self.page_failed.emit(idx, str(exc))
                self._save_session(idx + 1)
            except Exception as exc:
                logger.exception(f"Unexpected error on page {idx}")
                page.status = "failed"
                page.error_message = str(exc)
                self._db.save_page(page)
                self.page_failed.emit(idx, str(exc))
                self._save_session(idx + 1)

            if self._back_requested:
                self._back_requested = False
                self._current_index -= 1 if self._current_index > 0 else 0
            else:
                self._current_index += 1

        self._clear_session()
        self.finished.emit()

    async def _translate_page(
        self, page: Page, idx: int, total: int
    ) -> None:
        page.status = "translating"
        self._db.save_page(page)

        if self._source_language is None:
            text = " ".join(p.original_text for p in self._pages)
            self._source_language = detect_source_language(text)

        # Allow multiple rephrase attempts
        while True:
            self._rephrase_requested = False

            glossary_block = ""
            if self._glossary_mgr is not None:
                try:
                    glossary_block = self._glossary_mgr.format_for_prompt(
                        self._book_id
                    )
                except Exception:
                    logger.exception("Failed to build glossary block")

            context = build_context(self._pages, idx, n=2)

            messages = build_messages(
                original_text=page.original_text,
                context_block=context,
                glossary_block=glossary_block,
                style=self._job.style,
                source_language=self._source_language,
                target_language=self._job.target_language,
            )
            logger.debug(
                f"_translate_page[{idx}] system prompt: {messages[0]['content'][:200]}"
            )

            result = await self._engine.translate(
                messages=messages,
                model_id=self._job.model_id,
                temperature=float(self._job.temperature),
                top_p=float(self._job.top_p),
                max_tokens=self._job.max_tokens,
            )

            page.translated_text = result.text
            page.tokens_in = result.tokens_in
            page.tokens_out = result.tokens_out
            page.cost_usd = result.cost_usd
            page.model_id = result.model_id
            page.retry_count = 0
            page.error_message = None

            # --- interactive / hybrid review ---
            if self._job.mode in ("interactive", "hybrid"):
                edited = await self._wait_for_review(idx, page)
                if edited is None:
                    if self._rephrase_requested:
                        continue  # re-translate
                    break  # keep model translation, move on
                elif edited != page.translated_text:
                    old = page.translated_text or ""
                    page.translated_text = edited
                    page.is_manually_edited = True
                    from core.models import EditRecord
                    from datetime import datetime
                    page.edit_history.append(
                        EditRecord(
                            timestamp=datetime.now().isoformat(timespec="seconds"),
                            old_text=old,
                            new_text=edited,
                        )
                    )
                break
            else:
                break  # auto mode — no review

        page.status = "completed"
        self._db.save_page(page)
        logger.info(f"Page {idx} translated: {result.tokens_in} in / {result.tokens_out} out / ${result.cost_usd}")

        self._total_tokens_in += result.tokens_in
        self._total_tokens_out += result.tokens_out
        self._total_cost += result.cost_usd

        self.page_done.emit(idx, page.id)
        self.progress_changed.emit(idx + 1, total)
        self.interim_cost.emit(
            self._total_tokens_in,
            self._total_tokens_out,
            float(self._total_cost),
        )

        self._save_session(idx + 1)

    # ------------------------------------------------------------------
    # Interactive review
    # ------------------------------------------------------------------

    async def _wait_for_review(
        self, idx: int, page: Page
    ) -> str | None:
        self._review_future = asyncio.get_event_loop().create_future()
        self.needs_review.emit(idx, page.original_text, page.translated_text or "")
        try:
            edited = await asyncio.wait_for(self._review_future, timeout=None)
            return edited
        except asyncio.CancelledError:
            return None
        finally:
            self._review_future = None

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _save_session(self, next_index: int) -> None:
        try:
            self._db.save_session(
                book_id=self._book_id,
                mode=self._job.mode,
                translation_a_id=self._translation_id,
                current_page_index=next_index,
                is_paused=not self._pause_event.is_set(),
            )
        except Exception:
            logger.exception("Failed to save session state")

    def _clear_session(self) -> None:
        try:
            if not self._stop_requested:
                self._db.clear_session()
        except Exception:
            logger.exception("Failed to clear session state")


# ======================================================================
# Worker manager — handles single and dual-model (comparison) runs
# ======================================================================


class WorkerManager(QObject):
    """Coordinates one or two ``TranslationWorker`` instances.

    Signals mirror the workers and aggregate their state.
    """

    progress_changed = pyqtSignal(int, int)  # (done, total) — model A
    progress_b_changed = pyqtSignal(int, int)  # model B (only in comparison mode)
    all_finished = pyqtSignal()
    worker_finished = pyqtSignal(str)   # model id
    needs_review = pyqtSignal(int, str, str)  # index, original, translation
    interim_cost_a = pyqtSignal(int, int, float)  # tokens_in, tokens_out, cost_usd
    interim_cost_b = pyqtSignal(int, int, float)
    page_failed = pyqtSignal(int, str)  # index, error_message
    page_done = pyqtSignal(int, int)  # index, page_id
    error_occurred = pyqtSignal(str)  # critical error message

    def __init__(self, db: Database, engine: TranslatorEngine) -> None:
        super().__init__()
        self._db = db
        self._engine = engine
        self._worker_a: TranslationWorker | None = None
        self._worker_b: TranslationWorker | None = None
        self._task_a: asyncio.Task | None = None
        self._task_b: asyncio.Task | None = None
        self._glossary_mgr: GlossaryManager | None = None
        self._finished_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_glossary_manager(self, mgr: GlossaryManager) -> None:
        self._glossary_mgr = mgr

    def start(
        self,
        book_id: int,
        translation_a_id: int,
        job_a: TranslationJob,
        pages_a: list[Page],
        start_index_a: int = 0,
        translation_b_id: int | None = None,
        job_b: TranslationJob | None = None,
        pages_b: list[Page] | None = None,
        start_index_b: int = 0,
    ) -> None:
        self._finished_count = 0
        self._worker_a = TranslationWorker(
            db=self._db,
            engine=self._engine,
            book_id=book_id,
            translation_id=translation_a_id,
            job=job_a,
            pages=pages_a,
            current_index=start_index_a,
            glossary_mgr=self._glossary_mgr,
        )
        self._connect_signals(self._worker_a, "A")
        loop = asyncio.get_event_loop()
        self._task_a = loop.create_task(self._worker_a.run())

        if job_b is not None and translation_b_id is not None and pages_b is not None:
            self._worker_b = TranslationWorker(
                db=self._db,
                engine=self._engine,
                book_id=book_id,
                translation_id=translation_b_id,
                job=job_b,
                pages=pages_b,
                current_index=start_index_b,
                glossary_mgr=self._glossary_mgr,
            )
            self._connect_signals(self._worker_b, "B")
            self._task_b = loop.create_task(self._worker_b.run())

    def pause(self) -> None:
        if self._worker_a:
            self._worker_a.pause()
        if self._worker_b:
            self._worker_b.pause()

    def resume(self) -> None:
        if self._worker_a:
            self._worker_a.resume()
        if self._worker_b:
            self._worker_b.resume()

    def stop(self) -> None:
        if self._worker_a:
            self._worker_a.stop()
        if self._worker_b:
            self._worker_b.stop()

    def submit_review(self, edited_text: str | None, model: str = "A") -> None:
        if model == "A" and self._worker_a:
            self._worker_a.submit_review(edited_text)
        elif model == "B" and self._worker_b:
            self._worker_b.submit_review(edited_text)

    def go_back(self, model: str = "A") -> None:
        if model == "A" and self._worker_a:
            self._worker_a.go_back()
        elif model == "B" and self._worker_b:
            self._worker_b.go_back()

    def rephrase(self, model: str = "A") -> None:
        if model == "A" and self._worker_a:
            self._worker_a.rephrase()
        elif model == "B" and self._worker_b:
            self._worker_b.rephrase()

    def translate_page(self, idx: int, model: str = "A") -> None:
        """Translate a specific page on demand (e.g., from review panel)."""
        if model == "A" and self._worker_a:
            loop = asyncio.get_event_loop()
            loop.create_task(self._worker_a.translate_page(idx))
        elif model == "B" and self._worker_b:
            loop = asyncio.get_event_loop()
            loop.create_task(self._worker_b.translate_page(idx))

    @property
    def is_running(self) -> bool:
        return (
            (self._task_a is not None and not self._task_a.done())
            or (self._task_b is not None and not self._task_b.done())
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect_signals(
        self, worker: TranslationWorker, label: str
    ) -> None:
        worker.finished.connect(self._on_worker_finished)
        worker.needs_review.connect(self.needs_review.emit)
        worker.error_occurred.connect(self.error_occurred.emit)

        if label == "A":
            worker.progress_changed.connect(self.progress_changed.emit)
            worker.interim_cost.connect(self.interim_cost_a.emit)
        else:
            worker.progress_changed.connect(self.progress_b_changed.emit)
            worker.interim_cost.connect(self.interim_cost_b.emit)
        worker.page_failed.connect(self.page_failed.emit)
        worker.page_done.connect(self.page_done.emit)

    def _on_worker_finished(self) -> None:
        self._finished_count += 1
        sender = self.sender()
        if isinstance(sender, TranslationWorker):
            self.worker_finished.emit(sender._job.model_id)
        if self._finished_count >= 2 or (
            self._finished_count >= 1 and self._worker_b is None
        ):
            self.all_finished.emit()
