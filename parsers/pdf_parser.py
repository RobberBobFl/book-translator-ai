"""PDF book parser using PyMuPDF (fitz).

Extracts text per page in reading order. Text-based PDFs are handled fully;
**scanned (image-only) PDFs contain no text** and will yield an (almost) empty
book — OCR is a planned follow-up step, not handled here yet.

Headings are not explicitly marked in PDFs, so chapter detection relies on the
shared heuristic (keyword + number). Paragraph boundaries are taken from the
blank lines PyMuPDF inserts between blocks.
"""

from pathlib import Path

from loguru import logger

from parsers.base import BookParser
from core.models import Book

try:
    import fitz
except ImportError:  # pragma: no cover - fitz is a declared dependency
    fitz = None


class PdfParser(BookParser):
    """Parser for PDF documents."""

    SUPPORTED_EXTENSIONS = ["pdf"]

    def parse(self, file_path: str, chunk_size: int = 2000) -> Book:
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) is required for PDF import")

        path = Path(file_path)
        logger.info(f"Reading PDF: {path.name}")

        doc = fitz.open(str(path))
        lines: list[str] = []
        for page in doc:
            # sort=True keeps a sensible left-to-right, top-to-bottom order.
            text = page.get_text("text", sort=True)
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    lines.append(line)
        doc.close()

        text = "\n\n".join(lines)
        logger.info(f"PDF extracted {len(lines)} lines ({len(text)} chars)")
        return self.build_from_text(text, path.stem, str(path), "pdf", chunk_size=chunk_size)
