"""Markdown (.md) import parser — re-imports previously exported translations."""

import re
from pathlib import Path

from loguru import logger

from parsers.base import BookParser
from core.models import Book


# Regex for metadata lines in exported markdown
_META_RE = re.compile(r"^\*(\w+):\s(.+)\*$")


class MarkdownImportParser(BookParser):
    """Parser for Markdown files exported by this application."""

    SUPPORTED_EXTENSIONS = ["md", "markdown"]

    def parse(self, file_path: str) -> Book:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")

        logger.info(f"Reading MD: {path.name} ({len(text)} chars)")

        lines = text.split("\n")
        title = path.stem
        chapters: list[tuple[str, list[str]]] = []
        current_chapter_title = "Main Content"
        current_chapter_pars: list[str] = []
        in_metadata = True

        i = 0
        while i < len(lines):
            line = lines[i]

            # Title
            if line.startswith("# ") and not line.startswith("## "):
                title = line[2:].strip()
                i += 1
                continue

            # Metadata lines
            if in_metadata and _META_RE.match(line):
                i += 1
                continue

            # Separator
            if line.strip() == "---":
                in_metadata = False
                i += 1
                continue

            in_metadata = False

            # Chapter heading
            if line.startswith("## ") and not line.startswith("### "):
                if current_chapter_pars:
                    chapters.append((current_chapter_title, current_chapter_pars))
                current_chapter_title = line[3:].strip()
                current_chapter_pars = []
                i += 1
                continue

            # Page marker — ignore, just include text content
            if line.startswith("### "):
                i += 1
                continue

            if line.strip():
                current_chapter_pars.append(line)

            i += 1

        if current_chapter_pars:
            chapters.append((current_chapter_title, current_chapter_pars))

        if not chapters:
            chapters = [(title, ["(empty)"])]

        paragraphs = BookParser.split_paragraphs(
            "\n\n".join(
                p for _, pars in chapters for p in pars
            )
        )
        chapters = BookParser.group_into_chapters(paragraphs, title=title)
        pages = BookParser.split_into_pages(chapters)
        book = self.build_book(
            title=title,
            source_path=str(path),
            source_format="md",
            chapters=chapters,
            pages=pages,
        )

        self.check_integrity(file_path, book)
        return book
