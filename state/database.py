"""SQLite database abstraction with full CRUD for all entities."""

import json
import sqlite3
from pathlib import Path
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from core.models import (
    Book,
    Chapter,
    EditRecord,
    GlossaryEntry,
    Page,
    Translation,
)
from state.schema import migrate

if TYPE_CHECKING:
    from typing import Literal


class Database:
    """Manages SQLite connection and provides CRUD for all domain models."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def initialize(self) -> None:
        """Create tables and run migrations."""
        migrate(self.conn)

    # ------------------------------------------------------------------
    # Books
    # ------------------------------------------------------------------

    def save_book(self, book: Book, raw_translation_name: str = "raw") -> Book:
        conn = self.conn
        if book.id is None:
            total_pars = sum(len(ch.paragraphs) for ch in book.chapters)
            cursor = conn.execute(
                """INSERT INTO books (title, source_path, source_format, file_hash, total_paragraphs, total_pages)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    book.title,
                    book.source_path,
                    book.source_format,
                    book.file_hash,
                    total_pars,
                    len(book.pages),
                ),
            )
            assert cursor.lastrowid is not None
            book.id = cursor.lastrowid
        assert book.id is not None
        # Save translations that belong to this book
        for t in book.translations:
            if t.book_id == book.id or t.book_id == 0:
                t.book_id = book.id
                self.save_translation(t)
        # Auto-create a raw translation from pages
        if book.pages:
            has_translation = any(
                p.translation_id != 0 for p in book.pages
            )
            if not has_translation:
                raw_t = self.create_translation(
                    book_id=book.id,
                    name=raw_translation_name,
                    source_type="parallel",
                )
                for p in book.pages:
                    p.translation_id = raw_t.id
                    p.book_id = book.id
                    self.save_page(p)
        conn.commit()
        return book

    def load_book(self, book_id: int) -> Book | None:
        conn = self.conn
        row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if row is None:
            return None
        translations = self.list_translations(book_id)
        # Original pages belong to the book's first ("raw") translation, NOT to
        # every translation created later. Loading *all* pages made each new
        # translation treat previous translations' pages as "original" and
        # duplicate them on every start.
        raw_t = next((t for t in translations if t.name == "raw"), None)
        raw_id = (
            raw_t.id
            if raw_t is not None
            else (min((t.id for t in translations), default=None) if translations else None)
        )
        if raw_id is not None:
            page_rows = conn.execute(
                "SELECT * FROM pages WHERE book_id=? AND translation_id=? "
                "ORDER BY chapter_title, page_number",
                (book_id, raw_id),
            ).fetchall()
        else:
            page_rows = conn.execute(
                "SELECT * FROM pages WHERE book_id=? ORDER BY chapter_title, page_number",
                (book_id,),
            ).fetchall()
        book_pages = [self._row_to_page(p) for p in page_rows]
        # Build chapters from pages (group by chapter_title)
        chapters: dict[str, list[str]] = {}
        for p in book_pages:
            chapters.setdefault(p.chapter_title, []).append(p.original_text)
        return Book(
            id=row["id"],
            title=row["title"],
            source_path=row["source_path"],
            source_format=row["source_format"],
            file_hash=row["file_hash"],
            chapters=[
                Chapter(
                    title=t,
                    paragraphs=[],
                )
                for t in chapters
            ],
            pages=book_pages,
            translations=translations,
        )

    def get_book_by_path(self, path: str) -> Book | None:
        conn = self.conn
        row = conn.execute(
            "SELECT id FROM books WHERE source_path=?", (path,)
        ).fetchone()
        if row is None:
            return None
        return self.load_book(row["id"])

    def delete_book(self, book_id: int) -> None:
        self.conn.execute("DELETE FROM books WHERE id=?", (book_id,))
        self.conn.commit()

    def list_books(self) -> list[Book]:
        conn = self.conn
        rows = conn.execute("SELECT id FROM books ORDER BY updated_at DESC").fetchall()
        result: list[Book] = []
        for r in rows:
            book = self.load_book(r["id"])
            if book is not None:
                result.append(book)
        return result

    # ------------------------------------------------------------------
    # Translations
    # ------------------------------------------------------------------

    def create_translation(
        self,
        book_id: int,
        name: str,
        model_id: str | None = None,
        source_type: str = "parallel",
        mode: str = "auto",
    ) -> Translation:
        conn = self.conn
        cursor = conn.execute(
            """INSERT INTO translations (book_id, name, model_id, source_type, mode)
               VALUES (?, ?, ?, ?, ?)""",
            (book_id, name, model_id, source_type, mode),
        )
        conn.commit()
        assert cursor.lastrowid is not None
        return Translation(
            id=cursor.lastrowid,
            book_id=book_id,
            name=name,
            model_id=model_id,
            source_type=cast("Literal['parallel', 'imported', 'previous']", source_type),
            mode=cast("Literal['auto', 'interactive', 'hybrid']", mode),
            created_at="",
        )

    def save_translation(self, t: Translation) -> Translation:
        conn = self.conn
        if t.id == 0:
            cursor = conn.execute(
                """INSERT INTO translations (book_id, name, model_id, source_type, mode, total_cost, total_tokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (t.book_id, t.name, t.model_id, t.source_type, t.mode, str(t.total_cost), t.total_tokens),
            )
            assert cursor.lastrowid is not None
            t.id = cursor.lastrowid
        else:
            conn.execute(
                """UPDATE translations SET name=?, model_id=?, source_type=?, mode=?,
                   total_cost=?, total_tokens=? WHERE id=?""",
                (t.name, t.model_id, t.source_type, t.mode, str(t.total_cost), t.total_tokens, t.id),
            )
        conn.commit()
        return t

    def get_translation(self, translation_id: int) -> Translation | None:
        row = self.conn.execute(
            "SELECT * FROM translations WHERE id=?", (translation_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_translation(row)

    def list_translations(self, book_id: int) -> list[Translation]:
        rows = self.conn.execute(
            "SELECT * FROM translations WHERE book_id=? ORDER BY created_at", (book_id,)
        ).fetchall()
        return [self._row_to_translation(r) for r in rows]

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    def save_page(self, p: Page) -> Page:
        conn = self.conn
        edit_history_json = (
            json.dumps([e.model_dump() for e in p.edit_history], ensure_ascii=False)
            if p.edit_history
            else None
        )
        if p.id == 0:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO pages
                   (translation_id, book_id, chapter_title, page_number,
                    original_text, model_id, translated_text, status,
                    tokens_in, tokens_out, cost_usd, retry_count,
                    error_message, is_manually_edited, edit_history)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p.translation_id, p.book_id, p.chapter_title, p.page_number,
                    p.original_text, p.model_id, p.translated_text, p.status,
                    p.tokens_in, p.tokens_out, str(p.cost_usd), p.retry_count,
                    p.error_message, int(p.is_manually_edited), edit_history_json,
                ),
            )
            if cursor.lastrowid is not None and cursor.lastrowid != 0:
                p.id = cursor.lastrowid
            else:
                row = conn.execute(
                    """SELECT id FROM pages
                       WHERE translation_id=? AND chapter_title=? AND page_number=?""",
                    (p.translation_id, p.chapter_title, p.page_number),
                ).fetchone()
                if row is not None:
                    p.id = row["id"]
        else:
            conn.execute(
                """UPDATE pages SET translated_text=?, status=?, tokens_in=?,
                   tokens_out=?, cost_usd=?, retry_count=?, error_message=?,
                   is_manually_edited=?, edit_history=?, updated_at=datetime('now')
                   WHERE id=?""",
                (
                    p.translated_text, p.status, p.tokens_in, p.tokens_out,
                    str(p.cost_usd), p.retry_count, p.error_message,
                    int(p.is_manually_edited), edit_history_json, p.id,
                ),
            )
        conn.commit()
        return p

    def get_page(self, page_id: int) -> Page | None:
        row = self.conn.execute(
            "SELECT * FROM pages WHERE id=?", (page_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_page(row)

    def get_pages(self, translation_id: int) -> list[Page]:
        rows = self.conn.execute(
            "SELECT * FROM pages WHERE translation_id=? ORDER BY chapter_title, page_number",
            (translation_id,),
        ).fetchall()
        return [self._row_to_page(r) for r in rows]

    def get_pending_pages(self, translation_id: int) -> list[Page]:
        rows = self.conn.execute(
            """SELECT * FROM pages
               WHERE translation_id=? AND status IN ('pending', 'failed')
               ORDER BY chapter_title, page_number""",
            (translation_id,),
        ).fetchall()
        return [self._row_to_page(r) for r in rows]

    def count_completed_pages(self, translation_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM pages WHERE translation_id=? AND status='completed'",
            (translation_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # Glossary
    # ------------------------------------------------------------------

    def add_glossary_entry(self, entry: GlossaryEntry) -> GlossaryEntry:
        conn = self.conn
        cursor = conn.execute(
            """INSERT OR REPLACE INTO glossary (book_id, original_term, translated_term, is_auto_detected, context)
               VALUES (?, ?, ?, ?, ?)""",
            (entry.book_id, entry.original_term, entry.translated_term,
             int(entry.is_auto_detected), entry.context),
        )
        conn.commit()
        entry.id = cursor.lastrowid
        return entry

    def get_glossary(self, book_id: int) -> list[GlossaryEntry]:
        rows = self.conn.execute(
            "SELECT * FROM glossary WHERE book_id=? ORDER BY original_term", (book_id,)
        ).fetchall()
        return [self._row_to_glossary_entry(r) for r in rows]

    def update_glossary_entry(self, entry_id: int, translated_term: str) -> None:
        self.conn.execute(
            "UPDATE glossary SET translated_term=? WHERE id=?",
            (translated_term, entry_id),
        )
        self.conn.commit()

    def delete_glossary_entry(self, entry_id: int) -> None:
        self.conn.execute("DELETE FROM glossary WHERE id=?", (entry_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Session state
    # ------------------------------------------------------------------

    def save_session(
        self,
        book_id: int,
        mode: str = "auto",
        translation_a_id: int | None = None,
        translation_b_id: int | None = None,
        current_index: int = 0,
        current_page_index: int | None = None,
        system_prompt: str | None = None,
        is_paused: bool = False,
    ) -> None:
        conn = self.conn
        # Clear any existing session
        conn.execute("DELETE FROM session_state")
        idx = current_page_index if current_page_index is not None else current_index
        conn.execute(
            """INSERT INTO session_state
               (book_id, mode, translation_a_id, translation_b_id,
                current_page_index, system_prompt, is_paused)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (book_id, mode, translation_a_id, translation_b_id,
             idx, system_prompt, int(is_paused)),
        )
        conn.commit()

    def load_session(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM session_state LIMIT 1").fetchone()
        if row is None:
            return None
        return dict(row)

    def clear_session(self) -> None:
        self.conn.execute("DELETE FROM session_state")
        self.conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_page(row: sqlite3.Row) -> Page:
        edit_history: list[EditRecord] = []
        if row["edit_history"]:
            try:
                edit_history = [
                    EditRecord(**e) for e in json.loads(row["edit_history"])
                ]
            except (json.JSONDecodeError, TypeError):
                edit_history = []
        return Page(
            id=row["id"],
            translation_id=row["translation_id"],
            book_id=row["book_id"],
            chapter_title=row["chapter_title"],
            page_number=row["page_number"],
            original_text=row["original_text"],
            model_id=row["model_id"],
            translated_text=row["translated_text"],
            status=row["status"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            cost_usd=Decimal(str(row["cost_usd"])),
            retry_count=row["retry_count"],
            error_message=row["error_message"],
            is_manually_edited=bool(row["is_manually_edited"]),
            edit_history=edit_history,
        )

    @staticmethod
    def _row_to_translation(row: sqlite3.Row) -> Translation:
        return Translation(
            id=row["id"],
            book_id=row["book_id"],
            name=row["name"],
            model_id=row["model_id"],
            source_type=row["source_type"],
            mode=row["mode"],
            created_at=row["created_at"],
            total_cost=Decimal(str(row["total_cost"])) if row["total_cost"] else Decimal("0"),
            total_tokens=row["total_tokens"],
        )

    @staticmethod
    def _row_to_glossary_entry(row: sqlite3.Row) -> GlossaryEntry:
        return GlossaryEntry(
            id=row["id"],
            book_id=row["book_id"],
            original_term=row["original_term"],
            translated_term=row["translated_term"],
            is_auto_detected=bool(row["is_auto_detected"]),
            context=row["context"],
        )
