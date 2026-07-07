"""Abstract base parser and shared paragraph/chapter utilities."""

import re
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger

from core.models import Book, Chapter, Page, Paragraph
from utils.page_splitter import split_chapter_into_pages


class BookParser(ABC):
    """Base class for book format parsers."""

    SUPPORTED_EXTENSIONS: list[str] = []

    @abstractmethod
    def parse(self, file_path: str) -> Book:
        """Parse a book file and return a Book instance."""
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def split_paragraphs(text: str) -> list[str]:
        """Split text into paragraphs on blank lines and strip whitespace."""
        raw = re.split(r"\n\s*\n", text)
        paragraphs = [p.strip() for p in raw if p.strip()]
        if paragraphs:
            logger.info(f"split_paragraphs: {len(paragraphs)} paragraphs")
            logger.debug(f"  first: {paragraphs[0][:100]}...")
            logger.debug(f"  last:  {paragraphs[-1][:100]}...")
        else:
            logger.warning("split_paragraphs: no paragraphs found")
        return paragraphs

    @staticmethod
    def guess_chapter_title(line: str) -> str | None:
        """Try to detect a chapter heading from a line of text."""
        stripped = line.strip()
        if not stripped:
            return None
        lowered = stripped.lower()

        chapter_keywords = (
            "chapter", "chapter ", "chapter ", "chapter ",
            "chapter i", "chapter ii", "chapter iii",
            "chapter iv", "chapter v", "chapter vi",
            "chapter vii", "chapter viii", "chapter ix", "chapter x",
            "chapter 1", "chapter 2", "chapter 3", "chapter 4", "chapter 5",
            "chapter 6", "chapter 7", "chapter 8", "chapter 9", "chapter 10",
            "глава", "глава ", "section", "section ",
            "part", "part ", "часть", "часть ",
        )

        if lowered.startswith(chapter_keywords):
            return stripped
        # Also detect single-line ALL CAPS headings
        if len(stripped) < 100 and stripped.isupper() and len(stripped) > 3:
            return stripped
        return None

    @staticmethod
    def group_into_chapters(
        paragraphs: list[str],
        title: str = "Main Content",
    ) -> list[tuple[str, list[str]]]:
        """Try to group paragraphs into chapters by detecting headings.

        Returns a list of (chapter_title, paragraph_texts).
        """
        chapters: list[tuple[str, list[str]]] = []
        current_title = title
        current_pars: list[str] = []

        for para in paragraphs:
            guessed = BookParser.guess_chapter_title(para)
            if guessed and len(para) < 200:
                if current_pars:
                    chapters.append((current_title, current_pars))
                current_title = guessed
                current_pars = []
            else:
                current_pars.append(para)

        if current_pars:
            chapters.append((current_title, current_pars))

        return chapters if chapters else [(title, paragraphs)]

    @staticmethod
    def split_into_pages(
        chapters: list[tuple[str, list[str]]],
    ) -> list[tuple[str, list[str]]]:
        """Split each chapter's paragraphs into pages.

        Returns a list of ``(chapter_title, [page_text, ...])`` tuples.
        Empty chapters are silently skipped.
        """
        result: list[tuple[str, list[str]]] = []
        for ch_title, pars in chapters:
            if not pars:
                logger.warning(f"Chapter '{ch_title}' has no paragraphs, skipping")
                continue
            pages = split_chapter_into_pages(pars, chapter_title=ch_title)
            result.append((ch_title, pages))
        return result

    @staticmethod
    def build_book(
        title: str,
        source_path: str,
        source_format: str,
        chapters: list[tuple[str, list[str]]],
        pages: list[tuple[str, list[str]]] | None = None,
    ) -> Book:
        """Construct a Book from detected chapters and paragraphs.

        If *pages* is provided, the Book will also contain Page objects.
        """
        book_pages: list[Page] = []
        if pages:
            page_number = 0
            for ch_title, page_texts in pages:
                for pt in page_texts:
                    page_number += 1
                    book_pages.append(Page(
                        translation_id=0,
                        book_id=0,
                        chapter_title=ch_title,
                        page_number=page_number,
                        original_text=pt,
                        model_id="",
                    ))
            logger.info(
                f"Book '{title}': {len(pages)} chapters, {len(book_pages)} pages"
            )
        return Book(
            title=title,
            source_path=source_path,
            source_format=source_format,
            file_hash="",
            chapters=[
                Chapter(
                    title=ch_title,
                    paragraphs=[
                        Paragraph(
                            translation_id=0,
                            book_id=0,
                            chapter_title=ch_title,
                            paragraph_index=idx,
                            original_text=p,
                            model_id="",
                        )
                        for idx, p in enumerate(ch_pars)
                    ],
                )
                for ch_title, ch_pars in chapters
                if ch_pars  # skip empty chapters
            ],
            pages=book_pages,
        )

    @staticmethod
    def resolve_extension(file_path: str) -> str:
        return Path(file_path).suffix.lower().lstrip(".")

    @staticmethod
    def check_integrity(
        file_path: str,
        book: Book,
        raw_text: str | None = None,
    ) -> None:
        """Log integrity check for a parsed book.

        If *raw_text* is provided (e.g. for .txt), also compares total
        characters in pages vs the source text.
        """
        logger.info(f"Integrity check: {book.title}")
        logger.info(f"  chapters: {len(book.chapters)}, pages: {len(book.pages)}")
        if book.pages:
            total = sum(len(p.original_text) for p in book.pages)
            logger.info(f"  total chars in pages: {total}")
            if raw_text is not None and raw_text.strip():
                raw_len = len(raw_text)
                loss = raw_len - total
                loss_pct = loss / raw_len * 100
                if loss_pct > 5:
                    logger.error(
                        f"  ⚠️  DATA LOSS: {loss_pct:.2f}% "
                        f"({loss} chars missing)"
                    )
                else:
                    logger.info(
                        f"  ✅  text preserved ({loss_pct:.2f}% loss, "
                        f"expected from whitespace normalization)"
                    )
        else:
            logger.warning("  ⚠️  book has no pages")
