"""SQLite database abstraction with full CRUD for all entities."""

import json
import sqlite3
from pathlib import Path
from decimal import Decimal

from core.models import (
    Book,
    Chapter,
    EditRecord,
    GlossaryEntry,
    Paragraph,
    Provider,
    Translation,
)
from state.schema import migrate


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

    def save_book(self, book: Book) -> Book:
        conn = self.conn
        if book.id is None:
            cursor = conn.execute(
                """INSERT INTO books (title, source_path, source_format, file_hash, total_paragraphs)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    book.title,
                    book.source_path,
                    book.source_format,
                    book.file_hash,
                    sum(len(ch.paragraphs) for ch in book.chapters),
                ),
            )
            book.id = cursor.lastrowid
        else:
            conn.execute(
                """UPDATE books SET title=?, source_path=?, source_format=?, file_hash=?,
                   updated_at=datetime('now') WHERE id=?""",
                (book.title, book.source_path, book.source_format, book.file_hash, book.id),
            )
        # Save translations that belong to this book
        for t in book.translations:
            if t.book_id == book.id or t.book_id == 0:
                t.book_id = book.id
                self.save_translation(t)
        conn.commit()
        return book

    def load_book(self, book_id: int) -> Book | None:
        conn = self.conn
        row = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if row is None:
            return None
        translations = self.list_translations(book_id)
        paragraphs = conn.execute(
            "SELECT * FROM paragraphs WHERE book_id=? ORDER BY chapter_title, paragraph_index",
            (book_id,),
        ).fetchall()
        chapters: dict[str, list[Paragraph]] = {}
        for p in paragraphs:
            chapters.setdefault(p["chapter_title"], []).append(self._row_to_paragraph(p))
        return Book(
            id=row["id"],
            title=row["title"],
            source_path=row["source_path"],
            source_format=row["source_format"],
            file_hash=row["file_hash"],
            chapters=[Chapter(title=t, paragraphs=pp) for t, pp in chapters.items()],
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
        return [self.load_book(r["id"]) for r in rows if self.load_book(r["id"]) is not None]

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
        return Translation(
            id=cursor.lastrowid,
            book_id=book_id,
            name=name,
            model_id=model_id,
            source_type=source_type,
            mode=mode,
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
    # Paragraphs
    # ------------------------------------------------------------------

    def save_paragraph(self, p: Paragraph) -> Paragraph:
        conn = self.conn
        edit_history_json = json.dumps(
            [e.model_dump() for e in p.edit_history], ensure_ascii=False
        ) if p.edit_history else None
        if p.id == 0:
            cursor = conn.execute(
                """INSERT INTO paragraphs
                   (translation_id, book_id, chapter_title, paragraph_index,
                    original_text, model_id, translated_text, status,
                    tokens_in, tokens_out, cost_usd, retry_count,
                    error_message, is_manually_edited, edit_history)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p.translation_id, p.book_id, p.chapter_title, p.paragraph_index,
                    p.original_text, p.model_id, p.translated_text, p.status,
                    p.tokens_in, p.tokens_out, str(p.cost_usd), p.retry_count,
                    p.error_message, int(p.is_manually_edited), edit_history_json,
                ),
            )
            p.id = cursor.lastrowid
        else:
            conn.execute(
                """UPDATE paragraphs SET translated_text=?, status=?, tokens_in=?,
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

    def get_paragraph(self, paragraph_id: int) -> Paragraph | None:
        row = self.conn.execute(
            "SELECT * FROM paragraphs WHERE id=?", (paragraph_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_paragraph(row)

    def get_paragraphs(self, translation_id: int) -> list[Paragraph]:
        rows = self.conn.execute(
            "SELECT * FROM paragraphs WHERE translation_id=? ORDER BY chapter_title, paragraph_index",
            (translation_id,),
        ).fetchall()
        return [self._row_to_paragraph(r) for r in rows]

    def get_pending_paragraphs(self, translation_id: int) -> list[Paragraph]:
        rows = self.conn.execute(
            """SELECT * FROM paragraphs
               WHERE translation_id=? AND status IN ('pending', 'failed')
               ORDER BY chapter_title, paragraph_index""",
            (translation_id,),
        ).fetchall()
        return [self._row_to_paragraph(r) for r in rows]

    def count_completed(self, translation_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM paragraphs WHERE translation_id=? AND status='completed'",
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
        system_prompt: str | None = None,
        is_paused: bool = False,
    ) -> None:
        conn = self.conn
        # Clear any existing session
        conn.execute("DELETE FROM session_state")
        conn.execute(
            """INSERT INTO session_state
               (book_id, mode, translation_a_id, translation_b_id,
                current_paragraph_index, system_prompt, is_paused)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (book_id, mode, translation_a_id, translation_b_id,
             current_index, system_prompt, int(is_paused)),
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
    def _row_to_paragraph(row: sqlite3.Row) -> Paragraph:
        edit_history: list[EditRecord] = []
        if row["edit_history"]:
            try:
                edit_history = [
                    EditRecord(**e) for e in json.loads(row["edit_history"])
                ]
            except (json.JSONDecodeError, TypeError):
                edit_history = []
        return Paragraph(
            id=row["id"],
            translation_id=row["translation_id"],
            book_id=row["book_id"],
            chapter_title=row["chapter_title"],
            paragraph_index=row["paragraph_index"],
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
