"""Export a translation to Markdown (with optional EPUB/PDF via pandoc)."""

import subprocess
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
            for p in pages:
                if p.chapter_title != current_chapter:
                    current_chapter = p.chapter_title
                    lines.append(f"## {current_chapter}")
                    lines.append("")

                if include_original:
                    lines.append(f"### Страница {p.page_index + 1}")
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
                    if p.page_index == 0 or p.chapter_title != pages[p.page_index - 1].chapter_title:
                        lines.append(f"### Страница {p.page_index + 1}")
                        lines.append("")
                    lines.append(p.translated_text)
                    lines.append("")
                else:
                    lines.append(f"### Страница {p.page_index + 1}")
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


def convert_with_pandoc(
    md_path: str | Path,
    output_format: str = "epub",
    title: str = "",
) -> str:
    """Convert a Markdown file to EPUB or PDF using pandoc.

    Returns the path to the generated file.
    """
    md_path = Path(md_path)
    out_path = md_path.with_suffix(f".{output_format}")

    cmd = ["pandoc", str(md_path), "-o", str(out_path)]
    if title:
        cmd.extend(["--metadata", f"title={title}"])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Pandoc failed: {result.stderr.strip()}"
        )
    return str(out_path)
