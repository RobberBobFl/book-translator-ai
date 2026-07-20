"""Export a translation to Markdown (with optional EPUB/PDF via pandoc)."""

import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from loguru import logger

from state.database import Database


def check_translation_complete(db: Database, translation_id: int) -> bool:
    """Check if all paragraphs/pages in a translation have status 'completed'."""
    pages = db.get_pages(translation_id)
    if pages:
        completed = db.count_completed_pages(translation_id)
        total = len(pages)
        logger.info(f"Translation #{translation_id}: {completed}/{total} pages completed")
        return completed == total
    paras = db.get_paragraphs(translation_id)
    if not paras:
        logger.warning(f"Translation #{translation_id} has no paragraphs or pages")
        return False
    completed = db.count_completed(translation_id)
    total = len(paras)
    logger.info(f"Translation #{translation_id}: {completed}/{total} paragraphs completed")
    return completed == total


def export_to_markdown(
    db: Database,
    book_id: int,
    translation_id: int,
    output_path: str | Path,
    include_original: bool = False,
    use_pages: bool = True,
) -> str:
    """Export a translation to Markdown and return the file path.

    If *include_original* is ``True``, each paragraph/page shows the original
    followed by the translation.  When *use_pages* is ``True`` (the default)
    the exporter reads pages from the database; otherwise it falls back to
    paragraphs for legacy translations.
    """
    logger.info(f"Starting export to Markdown: book_id={book_id}, translation_id={translation_id}, path={output_path}")
    book = db.load_book(book_id)
    if book is None:
        logger.error(f"Book #{book_id} not found")
        raise ValueError(f"Book #{book_id} not found")
    trans = db.get_translation(translation_id)
    if trans is None:
        logger.error(f"Translation #{translation_id} not found")
        raise ValueError(f"Translation #{translation_id} not found")

    lines: list[str] = [
        f"# {book.title}",
        "",
        f"*Translation: {trans.name}*",
        f"*Model: {trans.model_id or 'N/A'}*",
        f"*Mode: {trans.mode}*",
        f"*Date: {trans.created_at}*",
        "",
        "---",
        "",
    ]

    if use_pages:
        pages = db.get_pages(translation_id)
        if pages:
            current_chapter = ""
            for idx, p in enumerate(pages):
                if p.chapter_title != current_chapter:
                    current_chapter = p.chapter_title
                    lines.append(f"## {current_chapter}")
                    lines.append("")

                if include_original:
                    lines.append(f"### Страница {idx + 1}")
                    lines.append("")
                    lines.append(f"Оригинал: {p.original_text}")
                    lines.append("")
                    if p.translated_text:
                        lines.append(f"Перевод: {p.translated_text}")
                    else:
                        lines.append("Перевод: *[not translated]*")
                    lines.append("")
                    lines.append("---")
                    lines.append("")
                elif p.translated_text:
                    if idx == 0 or p.chapter_title != pages[idx - 1].chapter_title:
                        lines.append(f"### Страница {idx + 1}")
                        lines.append("")
                    lines.append(p.translated_text)
                    lines.append("")
                else:
                    lines.append(f"### Страница {idx + 1}")
                    lines.append("")
                    lines.append("*[not translated]*")
                    lines.append("")
            logger.info(f"Exported {len(pages)} pages")
            output = Path(output_path)
            try:
                output.write_text("\n".join(lines), encoding="utf-8")
            except OSError as exc:
                logger.error(f"Failed to write Markdown file {output}: {exc}")
                raise
            logger.info(f"Successfully exported to {output}")
            return str(output)
        logger.info("No pages found, falling back to paragraphs")

    paras = db.get_paragraphs(translation_id)
    current_chapter = ""
    for p in paras:
        if p.chapter_title != current_chapter:
            current_chapter = p.chapter_title
            lines.append(f"## {current_chapter}")
            lines.append("")

        if include_original:
            lines.append(f"Оригинал: {p.original_text}")
            lines.append("")
            if p.translated_text:
                lines.append(f"Перевод: {p.translated_text}")
            else:
                lines.append("Перевод: *[not translated]*")
            lines.append("")
            lines.append("---")
            lines.append("")
        elif p.translated_text:
            lines.append(p.translated_text)
            lines.append("")
        else:
            lines.append("*[not translated]*")
            lines.append("")

    output = Path(output_path)
    try:
        output.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        logger.error(f"Failed to write Markdown file {output}: {exc}")
        raise
    logger.info(f"Successfully exported to {output}")
    return str(output)


def _resolve_pandoc() -> str | None:
    """Locate a usable pandoc executable.

    Resolution order:
    1. A ``pandoc`` already on ``PATH`` (user-managed).
    2. The binary bundled/downloaded by :mod:`pypandoc` (installed via the
       ``pypandoc-binary`` dependency, so it is normally available after
       ``uv sync`` without any manual step).

    Returns the executable path, or ``None`` if pandoc cannot be found.
    """
    # 1) Prefer a pandoc already on PATH.
    on_path = shutil.which("pandoc")
    if on_path:
        return on_path

    # 2) Fall back to pypandoc (downloads the binary on first use if needed).
    try:
        import pypandoc
    except ImportError:
        return None
    try:
        path = pypandoc.get_pandoc_path()
    except Exception:
        path = None
    if not path or not Path(path).exists():
        try:
            pypandoc.download_pandoc()
            path = pypandoc.get_pandoc_path()
        except Exception:
            return None
    return path


def pandoc_available() -> bool:
    """Return ``True`` if a pandoc executable can be located."""
    return _resolve_pandoc() is not None


def convert_with_pandoc(
    md_path: str | Path,
    output_format: str = "epub",
    title: str = "",
    output_path: str | Path | None = None,
) -> str:
    """Convert a Markdown file to EPUB or PDF using pandoc.

    If *output_path* is given it is used as the destination; otherwise the
    output is written next to *md_path* with the matching extension.

    Returns the path to the generated file.
    """
    md_path = Path(md_path)
    out_path = Path(output_path) if output_path else md_path.with_suffix(f".{output_format}")

    pandoc_bin = _resolve_pandoc()
    if pandoc_bin is None:
        raise RuntimeError(
            "Pandoc is not available. Ensure 'pypandoc-binary' is installed "
            "(uv sync) or install pandoc manually: https://pandoc.org/install.html"
        )

    cmd = [str(pandoc_bin), str(md_path), "-o", str(out_path)]
    if title:
        cmd.extend(["--metadata", f"title={title}"])
    # PDF needs an explicit engine; weasyprint is pip-installable (no LaTeX).
    if output_format == "pdf":
        cmd.extend(["--pdf-engine=weasyprint"])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Pandoc failed: {result.stderr.strip()}"
        )
    return str(out_path)


def export_to_fb2(
    db: Database,
    book_id: int,
    translation_id: int,
    output_path: str | Path,
    include_original: bool = False,
) -> str:
    """Export a translation to FictionBook 2.0 (FB2) and return the path.

    Chapters are rebuilt from the pages' ``chapter_title``; each chapter
    becomes an FB2 ``<section>``.  When *include_original* is ``True`` the
    original paragraph is emitted before its translation (so the FB2 file
    contains both).  No external tools (pandoc, etc.) are required.
    """
    logger.info(
        f"Starting export to FB2: book_id={book_id}, "
        f"translation_id={translation_id}, path={output_path}"
    )
    book = db.load_book(book_id)
    if book is None:
        logger.error(f"Book #{book_id} not found")
        raise ValueError(f"Book #{book_id} not found")
    trans = db.get_translation(translation_id)
    if trans is None:
        logger.error(f"Translation #{translation_id} not found")
        raise ValueError(f"Translation #{translation_id} not found")

    pages = db.get_pages(translation_id)
    if not pages:
        raise ValueError("No pages to export")

    fb_ns = "http://www.gribuser.ru/xml/fictionbook/2.0"
    ET.register_namespace("", fb_ns)
    root = ET.Element(f"{{{fb_ns}}}FictionBook")

    desc = ET.SubElement(root, f"{{{fb_ns}}}description")
    title_info = ET.SubElement(desc, f"{{{fb_ns}}}title-info")
    book_title = ET.SubElement(title_info, f"{{{fb_ns}}}book-title")
    book_title.text = book.title or "Book"

    body = ET.SubElement(root, f"{{{fb_ns}}}body")

    current_title: str | None = None
    section = None
    for p in pages:
        if p.chapter_title != current_title:
            current_title = p.chapter_title
            section = ET.SubElement(body, f"{{{fb_ns}}}section")
            if current_title and current_title not in ("t", "Глава", "Main Content"):
                title_el = ET.SubElement(section, f"{{{fb_ns}}}title")
                title_el.text = current_title
        if include_original and p.original_text:
            _append_paragraphs(section, p.original_text, fb_ns)
        if p.translated_text:
            _append_paragraphs(section, p.translated_text, fb_ns)
        elif not include_original:
            # Translation-only mode but page not translated yet: fall back
            # to the original so the chapter is not empty.
            _append_paragraphs(section, p.original_text or "", fb_ns)

    ET.indent(root)
    out = Path(output_path)
    try:
        out.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(root, encoding="unicode"),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.error(f"Failed to write FB2 file {out}: {exc}")
        raise
    logger.info(f"Successfully exported FB2 to {out}")
    return str(out)


def _append_paragraphs(section, text: str, fb_ns: str) -> None:
    """Split *text* on blank lines and append an FB2 ``<p>`` per paragraph."""
    for para in re.split(r"\n\s*\n", text or ""):
        para = para.strip()
        if not para:
            continue
        pe = ET.SubElement(section, f"{{{fb_ns}}}p")
        pe.text = para
