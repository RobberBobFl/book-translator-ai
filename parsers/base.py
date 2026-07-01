"""Abstract base parser and shared paragraph/chapter utilities."""

import re
from abc import ABC, abstractmethod
from pathlib import Path

from core.models import Book, Chapter, Paragraph


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
        return [p.strip() for p in raw if p.strip()]

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
    def build_book(
        title: str,
        source_path: str,
        source_format: str,
        chapters: list[tuple[str, list[str]]],
    ) -> Book:
        """Construct a Book from detected chapters and paragraphs."""
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
            ],
        )

    @staticmethod
    def resolve_extension(file_path: str) -> str:
        return Path(file_path).suffix.lower().lstrip(".")
