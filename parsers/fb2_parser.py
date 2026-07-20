"""FB2 (FictionBook 2.0) book parser.

FB2 is XML, but real-world files are frequently not perfectly well-formed
(mismatched/overlapping tags, unescaped ``&``, etc.). We therefore parse the
document with ``lxml`` in *recovery* mode, which tolerates such errors
instead of raising ``mismatched tag``.

Chapter structure is taken directly from the document: every top-level
``<section>`` becomes a chapter, using its ``<title>`` as the chapter title.
Nested sections are flattened into their parent chapter (their title is kept
as a paragraph so no text is lost). This makes headings like "Глава первая"
or "Chapter One" work correctly without any heuristic guessing.
"""

from pathlib import Path
from xml.etree import ElementTree as ET

from loguru import logger

from parsers.base import BookParser
from core.models import Book
from utils.hash_utils import compute_file_hash

_FB2_NS = "http://www.gribuser.ru/xml/fictionbook/2.0"
_BODY_LOCAL = "body"
_SECTION_LOCAL = "section"
_TITLE_LOCAL = "title"
# Block elements whose text becomes a paragraph.
_TEXT_LOCALS = frozenset({
    "p", "subtitle", "epigraph", "text-author", "cite", "v", "stanza",
})


def _local(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1]


class Fb2Parser(BookParser):
    """Parser for FB2 e-books."""

    SUPPORTED_EXTENSIONS = ["fb2"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, file_path: str, chunk_size: int = 2000) -> Book:
        path = Path(file_path)
        logger.info(f"Reading FB2: {path.name}")

        root = self._parse_xml(path)
        if root is None:
            raise ValueError(f"Не удалось разобрать FB2: {path.name}")

        chapters: list[tuple[str, list[str]]] = []
        all_blocks: list[str] = []
        self._walk(root, chapters, all_blocks)

        if not chapters:
            logger.warning("FB2: no sections found, falling back to flat text")
            text = "\n\n".join(all_blocks)
            return self.build_from_text(
                text, path.stem, str(path), "fb2", chunk_size=chunk_size
            )

        pages = self.split_into_pages(chapters, max_page_chars=chunk_size)
        book = self.build_book(
            title=path.stem,
            source_path=str(path),
            source_format="fb2",
            chapters=chapters,
            pages=pages,
        )
        book.file_hash = compute_file_hash(str(path))
        self.check_integrity(str(path), book, raw_text="\n\n".join(all_blocks))
        return book

    # ------------------------------------------------------------------
    # Tolerant XML parsing
    # ------------------------------------------------------------------

    def _parse_xml(self, path: Path):
        # 1) lxml with recovery — tolerates malformed real-world FB2 files
        #    (the user hit "mismatched tag" with the strict stdlib parser).
        try:
            from lxml import etree as LET
            parser = LET.XMLParser(recover=True, huge_tree=True)
            tree = LET.parse(str(path), parser)
            if tree is not None:
                return tree.getroot()
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(f"lxml parse failed ({exc}); using stdlib")
        # 2) stdlib strict parser (last resort; raises on malformed XML).
        try:
            return ET.parse(str(path)).getroot()
        except ET.ParseError as exc:
            logger.error(f"FB2 parse error: {exc}")
            raise

    # ------------------------------------------------------------------
    # Structure walk
    # ------------------------------------------------------------------

    def _walk(self, root, chapters, all_blocks) -> None:
        bodies = [
            c for c in root
            if _local(c.tag) == _BODY_LOCAL and c.get("name") is None
        ]
        if not bodies:
            bodies = [c for c in root if _local(c.tag) == _BODY_LOCAL] or [root]

        section_count = 0
        for body in bodies:
            pre_pars: list[str] = []
            for child in body:
                cl = _local(child.tag)
                if cl == _SECTION_LOCAL:
                    if pre_pars:
                        chapters.append(("Введение", pre_pars))
                        all_blocks.extend(pre_pars)
                        pre_pars = []
                    section_count += 1
                    title = self._section_title(child) or f"Глава {section_count}"
                    pars = self._collect_section_text(child)
                    if pars:
                        chapters.append((title, pars))
                        all_blocks.extend(pars)
                elif cl == _TITLE_LOCAL:
                    continue  # book title at body level — redundant
                else:
                    t = self._clean(child)
                    if t:
                        pre_pars.append(t)
                        all_blocks.append(t)
            if pre_pars:
                chapters.append(("Введение", pre_pars))
                all_blocks.extend(pre_pars)

    def _collect_section_text(self, elem) -> list[str]:
        """Return all paragraph texts inside a section, in document order.

        Nested ``<section>`` elements are flattened: their ``<title>`` is kept
        as a paragraph so the text is preserved.
        """
        out: list[str] = []
        for child in elem:
            cl = _local(child.tag)
            if cl == _TITLE_LOCAL:
                t = self._clean(child)
                if t:
                    out.append(t)
            elif cl == _SECTION_LOCAL:
                out.extend(self._collect_section_text(child))
            else:
                t = self._clean(child)
                if t:
                    out.append(t)
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _section_title(section_elem) -> str:
        for child in section_elem:
            if _local(child.tag) == _TITLE_LOCAL:
                return " ".join("".join(child.itertext()).split())
        return ""

    @staticmethod
    def _clean(elem) -> str:
        return " ".join("".join(elem.itertext()).split())
