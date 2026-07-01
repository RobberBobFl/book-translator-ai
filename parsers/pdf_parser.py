"""PDF book parser using PyMuPDF (fitz)."""

from pathlib import Path

import fitz

from parsers.base import BookParser
from core.models import Book
from utils.hash_utils import compute_file_hash


class PdfParser(BookParser):
    """Parser for PDF files using PyMuPDF."""

    SUPPORTED_EXTENSIONS = ["pdf"]

    def parse(self, file_path: str) -> Book:
        path = Path(file_path)
        doc = fitz.open(str(path))
        title = path.stem

        # Extract text from all pages
        all_paragraphs: list[tuple[float, str]] = []  # (y_position, text_block)
        for page in doc:
            blocks = page.get_text("blocks")
            for block in blocks:
                # block: (x, y, w, h, text, block_type, ...)
                if len(block) >= 5 and isinstance(block[4], str) and block[4].strip():
                    text = block[4].strip()
                    y_pos = block[1]
                    all_paragraphs.append((y_pos, text))

        # Sort by y position on each page, page by page
        sorted_texts = [t for _, t in all_paragraphs]

        # Try to detect chapters
        raw_pars = self.split_paragraphs("\n\n".join(sorted_texts))
        chapters = self.group_into_chapters(raw_pars, title=title)

        book = self.build_book(
            title=title,
            source_path=str(path),
            source_format="pdf",
            chapters=chapters,
        )
        book.file_hash = compute_file_hash(file_path)
        doc.close()
        return book
