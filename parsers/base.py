"""Abstract base parser and shared paragraph/chapter utilities."""

import re
from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger

from core.models import Book, Chapter, Page, Paragraph
from utils.hash_utils import compute_file_hash
from utils.page_splitter import split_chapter_into_pages


# ---------------------------------------------------------------------------
# Chapter-heading detection
# ---------------------------------------------------------------------------
# Keywords that may introduce a heading. A word boundary (\b) is required so
# that words like "participate" / "chapters" are NOT mistaken for headings.
# The value after the keyword must be a number or roman numeral: spelled-out
# numbers are intentionally ignored because a *missed* heading is far safer
# than a body line wrongly dropped as a heading (the user's #1 concern).
_HEADING_KEYWORD_RE = re.compile(
    r"^(глава|chapter|часть|part|section|раздел|том|book|act|scene|"
    r"действие|явление)\b[\s:.\-]+([0-9]+|[ivxlcdm]+)",
    re.IGNORECASE,
)
# Whole-line standalone heading words (case-insensitive).
_HEADING_WORDS = {
    "пролог", "эпилог", "введение", "заключение", "приложение",
    "послесловие", "благодарности", "предисловие", "глоссарий",
    "prologue", "epilogue", "introduction", "foreword", "afterword",
    "preface", "appendix", "acknowledgements", "acknowledgments",
    "glossary", "bibliography",
}
# A line that is only a roman numeral or a short number — classic markers.
_STANDALONE_NUMBER_RE = re.compile(r"^[ivxlcdm]+$|^[0-9]{1,3}$", re.IGNORECASE)
# Upper bound on heading length: longer lines are body text, never headings.
_MAX_HEADING_LEN = 80


class BookParser(ABC):
    """Base class for book format parsers."""

    SUPPORTED_EXTENSIONS: list[str] = []

    @abstractmethod
    def parse(self, file_path: str, chunk_size: int = 2000) -> Book:
        """Parse a book file and return a Book instance.

        *chunk_size* is the maximum number of source characters packed into
        a single translation page (passed through to the page splitter).
        """
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
        if not stripped or len(stripped) > _MAX_HEADING_LEN:
            return None
        lowered = stripped.lower()

        # 1) Keyword + number/roman value, e.g. "Глава 1", "Chapter I",
        #    "Part 3".  The \b word boundary prevents false hits like
        #    "participate" or "chapters".
        if _HEADING_KEYWORD_RE.match(lowered):
            return stripped

        # 2) Standalone known heading word, e.g. "Пролог", "Epilogue".
        if lowered in _HEADING_WORDS:
            return stripped

        # 3) Standalone roman numeral / short number, e.g. "I", "II", "12".
        if _STANDALONE_NUMBER_RE.match(stripped):
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
            if guessed:
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
        max_page_chars: int = 2000,
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
            pages = split_chapter_into_pages(pars, max_page_chars=max_page_chars, chapter_title=ch_title)
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

    # ------------------------------------------------------------------
    # Shared extraction pipeline
    # ------------------------------------------------------------------

    @staticmethod
    def build_from_text(
        text: str,
        title: str,
        source_path: str,
        source_format: str,
        chunk_size: int = 2000,
    ) -> Book:
        """Run the shared extract → chapter → page pipeline on raw text.

        Used by every concrete parser so behaviour (and the text-loss
        guarantee from :meth:`check_integrity`) is identical across formats.
        """
        paragraphs = BookParser.split_paragraphs(text)
        chapters = BookParser.group_into_chapters(paragraphs, title=title)
        pages = BookParser.split_into_pages(chapters, max_page_chars=chunk_size)
        book = BookParser.build_book(
            title=title,
            source_path=source_path,
            source_format=source_format,
            chapters=chapters,
            pages=pages,
        )
        book.file_hash = compute_file_hash(source_path)
        BookParser.check_integrity(source_path, book, raw_text=text)
        return book
