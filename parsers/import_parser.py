"""Import parser — reuses existing parsers to load a pre-existing translation.

Legacy: импорт готовых переводов поабзацно. Не использовать для нового кода.
Новые книги загружаются через парсеры напрямую, без этой обёртки.
"""

from pathlib import Path

from parsers.base import BookParser
from parsers.epub_parser import EpubParser
from parsers.fb2_parser import Fb2Parser
from parsers.markdown_import_parser import MarkdownImportParser
from parsers.pdf_parser import PdfParser
from parsers.txt_parser import TxtParser
from core.models import Book


_PARSER_MAP: dict[str, type[BookParser]] = {
    "epub": EpubParser,
    "fb2": Fb2Parser,
    "md": MarkdownImportParser,
    "markdown": MarkdownImportParser,
    "pdf": PdfParser,
    "txt": TxtParser,
}


def import_translation(file_path: str) -> Book:
    """Parse a translated book file for comparison.

    Supports the same formats as source books.
    The returned Book behaves the same way — chapters with paragraphs —
    but can be stored as ``source_type='imported'``.
    """
    ext = Path(file_path).suffix.lower().lstrip(".")
    parser_cls = _PARSER_MAP.get(ext)
    if parser_cls is None:
        raise ValueError(f"Unsupported format for import: .{ext}")
    return parser_cls().parse(file_path)
