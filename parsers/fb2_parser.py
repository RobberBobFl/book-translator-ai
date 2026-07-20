"""FB2 (FictionBook 2.0) book parser.

FB2 is plain XML. We walk the tree and collect text from <p>, <subtitle>,
<epigraph>, <text-author> and section <title> elements, in document order,
preserving paragraph boundaries. The stream is then run through the shared
pipeline, where section titles are re-detected as chapter headings.
"""

from pathlib import Path
import xml.etree.ElementTree as ET
from loguru import logger

from parsers.base import BookParser
from core.models import Book

_FB2_NS = "{http://www.gribuser.ru/xml/fictionbook/2.0}"


class Fb2Parser(BookParser):
    """Parser for FB2 e-books."""

    SUPPORTED_EXTENSIONS = ["fb2"]

    def parse(self, file_path: str, chunk_size: int = 2000) -> Book:
        path = Path(file_path)
        logger.info(f"Reading FB2: {path.name}")

        tree = ET.parse(str(path))
        root = tree.getroot()

        paragraphs: list[str] = []
        self._walk(root, paragraphs, parent_local="")

        text = "\n\n".join(paragraphs)
        logger.info(f"FB2 extracted {len(paragraphs)} blocks ({len(text)} chars)")
        return self.build_from_text(text, path.stem, str(path), "fb2", chunk_size=chunk_size)

    # ------------------------------------------------------------------
    # Tree walk
    # ------------------------------------------------------------------

    def _walk(self, elem: ET.Element, out: list[str], parent_local: str) -> None:
        tag = elem.tag
        local = tag.split("}", 1)[-1] if isinstance(tag, str) else ""

        if local == "title" and parent_local == "section":
            # A section title → keep it as a standalone line (becomes a heading).
            text = " ".join("".join(elem.itertext()).split())
            if text:
                out.append(text)
        elif (
            local in ("p", "subtitle", "epigraph", "text-author", "cite")
            and parent_local != "title"
        ):
            text = " ".join("".join(elem.itertext()).split())
            if text:
                out.append(text)

        for child in elem:
            self._walk(child, out, local)
