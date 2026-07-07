"""Import parser — reuses existing parsers to load a pre-existing translation.

Legacy: импорт готовых переводов. Новые книги загружаются через парсеры напрямую.
"""

from pathlib import Path

from parsers.base import BookParser
from parsers.markdown_import_parser import MarkdownImportParser
from parsers.txt_parser import TxtParser
from core.models import Book


_PARSER_MAP: dict[str, type[BookParser]] = {
    "md": MarkdownImportParser,
    "markdown": MarkdownImportParser,
    "txt": TxtParser,
}


def import_translation(file_path: str) -> Book:
    ext = Path(file_path).suffix.lower().lstrip(".")
    parser_cls = _PARSER_MAP.get(ext)
    if parser_cls is None:
        raise ValueError(f"Unsupported format for import: .{ext}")
    return parser_cls().parse(file_path)
