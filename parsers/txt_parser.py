"""Plain-text (.txt) book parser."""

from pathlib import Path

from loguru import logger

from parsers.base import BookParser
from core.models import Book


class TxtParser(BookParser):
    """Parser for plain text files."""

    SUPPORTED_EXTENSIONS = ["txt"]

    def parse(self, file_path: str, chunk_size: int = 2000) -> Book:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8", errors="replace")

        file_size = path.stat().st_size
        logger.info(f"Reading: {path.name} ({len(text)} chars, {file_size} bytes)")

        return self.build_from_text(text, path.stem, str(path), "txt", chunk_size=chunk_size)
