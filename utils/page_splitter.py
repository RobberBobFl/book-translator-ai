"""Split book chapters into pages for page-by-page translation."""

from loguru import logger
from translator.chunker import _split_sentences


def split_chapter_into_pages(
    paragraphs: list[str],
    max_page_chars: int = 2000,
    max_chapter_chars: int = 5000,
    chapter_title: str = "",
) -> list[str]:
    """Split a chapter's paragraphs into pages.

    Strategy:
    - If total chapter length ≤ *max_chapter_chars* → one page.
    - Otherwise, greedily pack paragraphs into pages of ≤ *max_page_chars*.
    - If a single paragraph exceeds *max_page_chars*, it is split by
      sentence boundaries.

    Returns a list of page texts (already joined with ``\\n\\n``).
    """
    if not paragraphs:
        logger.info(f"Chapter '{chapter_title}': empty, 0 pages")
        return []

    total_chars = sum(len(p) for p in paragraphs)

    if total_chars <= max_chapter_chars:
        logger.info(
            f"Chapter '{chapter_title}': {len(paragraphs)} paragraphs "
            f"({total_chars} chars) → 1 page"
        )
        return ["\n\n".join(paragraphs)]

    pages: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        # If a single paragraph exceeds the page limit, split by sentences
        if para_len > max_page_chars:
            if current:
                pages.append("\n\n".join(current))
                current = []
                current_len = 0
            sentences = _split_sentences(para)
            for page_text in _group_into_pages(sentences, max_page_chars):
                pages.append(page_text)
            continue

        # If adding this paragraph would exceed the limit, close current page
        if current and current_len + para_len + 2 > max_page_chars:
            pages.append("\n\n".join(current))
            current = []
            current_len = 0

        current.append(para)
        current_len += para_len + (2 if current else 0)

    if current:
        pages.append("\n\n".join(current))

    logger.info(
        f"Chapter '{chapter_title}': {len(paragraphs)} paragraphs "
        f"({total_chars} chars) → {len(pages)} pages"
    )
    return pages


def _group_into_pages(sentences: list[str], max_chars: int) -> list[str]:
    """Group sentences into pages respecting the char limit."""
    pages: list[str] = []
    current: list[str] = []
    current_len = 0
    for sent in sentences:
        sent_len = len(sent) + 1
        if current_len + sent_len > max_chars and current:
            pages.append(" ".join(current))
            current = []
            current_len = 0
        current.append(sent)
        current_len += sent_len
    if current:
        pages.append(" ".join(current))
    return pages
