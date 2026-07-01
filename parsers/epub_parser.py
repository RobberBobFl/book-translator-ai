"""EPUB book parser using ebooklib."""

from pathlib import Path

from ebooklib import epub

from parsers.base import BookParser
from core.models import Book
from utils.hash_utils import compute_file_hash


class EpubParser(BookParser):
    """Parser for EPUB files using ebooklib."""

    SUPPORTED_EXTENSIONS = ["epub"]

    def parse(self, file_path: str) -> Book:
        path = Path(file_path)
        book_epub = epub.read_epub(str(path))
        title = self._extract_title(book_epub) or path.stem
        chapters_text = self._extract_chapters(book_epub)
        chapters = []
        for ch_title, html_content in chapters_text:
            text = self._html_to_text(html_content)
            paragraphs = self.split_paragraphs(text)
            if paragraphs:
                chapters.append((ch_title, paragraphs))

        if not chapters:
            chapters = [(title, [])]

        book = self.build_book(
            title=title,
            source_path=str(path),
            source_format="epub",
            chapters=chapters,
        )
        book.file_hash = compute_file_hash(file_path)
        return book

    # ------------------------------------------------------------------

    @staticmethod
    def _extract_title(book_epub: epub.EpubBook) -> str | None:
        try:
            return book_epub.get_metadata("DC", "title")[0][0]
        except (IndexError, KeyError):
            return None

    @staticmethod
    def _extract_chapters(
        book_epub: epub.EpubBook,
    ) -> list[tuple[str, str]]:
        """Return list of (chapter_title, raw_html) from the EPUB TOC."""
        items = book_epub.get_items_of_type(ebooklib.ITEM_DOCUMENT)
        toc = book_epub.toc

        # Build a map of item href → title from the TOC
        href_title_map: dict[str, str] = {}
        for entry in _flatten_toc(toc):
            if isinstance(entry, tuple) and len(entry) == 2:
                link, title_obj = entry
                if hasattr(link, "href"):
                    href = link.href.split("#")[0]
                    href_title_map[href] = str(title_obj)

        chapters: list[tuple[str, str]] = []
        for item in items:
            href = item.get_name()
            title = href_title_map.get(href, Path(href).stem)
            content = item.get_content()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            chapters.append((title, content))

        return chapters

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip HTML tags, decode common entities, return plain text."""
        import html as html_mod
        import re

        # Remove <style> and <script> blocks
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)

        # Remove <br> and block-level tags → newlines
        html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        for tag in ("p", "div", "h[1-6]", "blockquote", "li", "tr", "th", "td"):
            html = re.sub(f"</?{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)

        # Decode entities
        text = html_mod.unescape(html)

        # Strip remaining tags
        text = re.sub(r"<[^>]+>", "", text)

        # Collapse whitespace
        text = re.sub(r" +", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _flatten_toc(toc: list) -> list:
    """Recursively flatten EPUB TOC structure."""
    result: list = []
    for item in toc:
        if isinstance(item, list):
            result.extend(_flatten_toc(item))
        elif isinstance(item, tuple):
            result.append(item)
            # Some TOC items have nested children
            if len(item) > 1 and isinstance(item[1], list):
                result.extend(_flatten_toc(item[1]))
    return result
