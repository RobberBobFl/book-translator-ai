"""Plain-text (.txt) book parser."""

from pathlib import Path

from parsers.base import BookParser
from core.models import Book
from utils.hash_utils import compute_file_hash


class TxtParser(BookParser):
    """Parser for plain text files."""

    SUPPORTED_EXTENSIONS = ["txt"]

    def parse(self, file_path: str) -> Book:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        paragraphs = self.split_paragraphs(text)
        chapters = self.group_into_chapters(paragraphs, title=path.stem)
        book = self.build_book(
            title=path.stem,
            source_path=str(path),
            source_format="txt",
            chapters=chapters,
        )
        book.file_hash = compute_file_hash(file_path)
        return book
