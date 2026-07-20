"""EPUB book parser using ebooklib + lxml.

Extracts block-level text (paragraphs, headings, list items) from every
XHTML document in the book's spine, in reading order, then feeds it through
the shared :meth:`BookParser.build_from_text` pipeline. No text is dropped:
headings stay in the stream and are later re-detected as chapter titles.
"""

from pathlib import Path

from ebooklib import epub, ITEM_DOCUMENT
from lxml import etree
from loguru import logger

from parsers.base import BookParser
from core.models import Book

# Block-level elements whose text we keep (in document order).
_BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "blockquote", "td", "th", "caption",
}
# Elements we never want as content.
_SKIP_TAGS = {"script", "style", "head", "title"}


def _local(tag: str) -> str:
    """Return an element's local name, stripping any XML namespace."""
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


class EpubParser(BookParser):
    """Parser for EPUB e-books."""

    SUPPORTED_EXTENSIONS = ["epub"]

    def parse(self, file_path: str, chunk_size: int = 2000) -> Book:
        path = Path(file_path)
        logger.info(f"Reading EPUB: {path.name}")

        book_epub = epub.read_epub(str(path))
        paragraphs: list[str] = []

        for item in book_epub.get_items_of_type(ITEM_DOCUMENT):
            # The EPUB navigation document is not book content.
            if isinstance(item, epub.EpubNav):
                continue

            try:
                root = etree.fromstring(item.get_content())
            except etree.XMLSyntaxError:
                # EPUBs are usually XHTML (HTML), not strict XML — lxml then
                # tags elements with the XHTML namespace, so we compare on the
                # local name below.
                root = etree.fromstring(
                    item.get_content(), parser=etree.HTMLParser()
                )

            # Drop non-content nodes (title, scripts, styles).
            for bad in [e for e in root.iter() if _local(e.tag) in _SKIP_TAGS]:
                parent = bad.getparent()
                if parent is not None:
                    parent.remove(bad)

            for el in root.iter():
                if _local(el.tag) in _BLOCK_TAGS:
                    text = " ".join("".join(el.itertext()).split())
                    if text:
                        paragraphs.append(text)

        text = "\n\n".join(paragraphs)
        logger.info(f"EPUB extracted {len(paragraphs)} blocks ({len(text)} chars)")
        return self.build_from_text(text, path.stem, str(path), "epub", chunk_size=chunk_size)
