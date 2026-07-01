"""FictionBook (.fb2) parser using lxml."""

from pathlib import Path

from lxml import etree

from parsers.base import BookParser
from core.models import Book
from utils.hash_utils import compute_file_hash

NS = {
    "fb": "http://www.gribuser.ru/xml/fictionbook/2.0",
}


class Fb2Parser(BookParser):
    """Parser for FictionBook (FB2) XML files."""

    SUPPORTED_EXTENSIONS = ["fb2"]

    def parse(self, file_path: str) -> Book:
        path = Path(file_path)
        tree = etree.parse(str(path))
        root = tree.getroot()

        title = self._extract_title(root) or path.stem
        body = root.find(".//fb:body", NS)
        chapters: list[tuple[str, list[str]]] = []

        if body is not None:
            sections = body.findall("fb:section", NS)
            if sections:
                for section in sections:
                    ch_title = self._extract_section_title(section)
                    paragraphs = self._extract_section_text(section)
                    if paragraphs:
                        chapters.append((ch_title, paragraphs))
            else:
                # No sections — treat entire body as one chapter
                paragraphs = self._extract_element_text(body)
                if paragraphs:
                    chapters.append((title, paragraphs))

        if not chapters:
            chapters = [(title, [])]

        book = self.build_book(
            title=title,
            source_path=str(path),
            source_format="fb2",
            chapters=chapters,
        )
        book.file_hash = compute_file_hash(file_path)
        return book

    # ------------------------------------------------------------------

    @staticmethod
    def _extract_title(root: etree._Element) -> str | None:
        title_info = root.find(".//fb:title-info/fb:book-title", NS)
        if title_info is not None and title_info.text:
            return title_info.text.strip()
        return None

    @staticmethod
    def _extract_section_title(section: etree._Element) -> str:
        title_el = section.find("fb:title", NS)
        if title_el is not None:
            parts = []
            for child in title_el.itertext():
                text = child.strip()
                if text:
                    parts.append(text)
            if parts:
                return " ".join(parts)
        return "Untitled Section"

    @staticmethod
    def _extract_section_text(section: etree._Element) -> list[str]:
        paragraphs: list[str] = []
        for child in section.iterchildren():
            if child.tag == f"{{{NS['fb']}}}title":
                continue
            if child.tag == f"{{{NS['fb']}}}section":
                continue
            text = "".join(child.itertext()).strip()
            if text:
                paragraphs.append(text)
        return paragraphs

    @staticmethod
    def _extract_element_text(element: etree._Element) -> list[str]:
        paragraphs: list[str] = []
        for child in element.iter():
            if child.tag == f"{{{NS['fb']}}}p":
                text = "".join(child.itertext()).strip()
                if text:
                    paragraphs.append(text)
        return paragraphs
