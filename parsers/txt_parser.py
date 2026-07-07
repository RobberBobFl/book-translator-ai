"""Plain-text (.txt) book parser."""

from pathlib import Path

from loguru import logger

from parsers.base import BookParser
from core.models import Book
from utils.hash_utils import compute_file_hash


class TxtParser(BookParser):
    """Parser for plain text files."""

    SUPPORTED_EXTENSIONS = ["txt"]

    def parse(self, file_path: str) -> Book:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")

        file_size = path.stat().st_size
        logger.info(f"Reading: {path.name} ({len(text)} chars, {file_size} bytes)")

        paragraphs = self.split_paragraphs(text)
        chapters = self.group_into_chapters(paragraphs, title=path.stem)
        pages = self.split_into_pages(chapters)
        book = self.build_book(
            title=path.stem,
            source_path=str(path),
            source_format="txt",
            chapters=chapters,
            pages=pages,
        )
        book.file_hash = compute_file_hash(file_path)

        self.check_integrity(file_path, book, raw_text=text)
        return book
