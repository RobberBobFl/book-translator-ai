"""Export a translation to Markdown (with optional EPUB/PDF via pandoc)."""

import subprocess
from pathlib import Path

from state.database import Database


def export_to_markdown(
    db: Database,
    book_id: int,
    translation_id: int,
    output_path: str | Path,
    include_original: bool = False,
) -> str:
    """Export a translation to Markdown and return the file path.

    If *include_original* is ``True``, each paragraph shows the original
    followed by the translation.
    """
    book = db.load_book(book_id)
    if book is None:
        raise ValueError(f"Book #{book_id} not found")
    trans = db.get_translation(translation_id)
    if trans is None:
        raise ValueError(f"Translation #{translation_id} not found")
    paras = db.get_paragraphs(translation_id)

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

    current_chapter = ""
    for p in paras:
        if p.chapter_title != current_chapter:
            current_chapter = p.chapter_title
            lines.append(f"## {current_chapter}")
            lines.append("")

        if include_original and p.translated_text:
            lines.append(f"> {p.original_text}")
            lines.append("")
            lines.append(p.translated_text)
        elif p.translated_text:
            lines.append(p.translated_text)
        else:
            lines.append("*[not translated]*")
        lines.append("")

    output = Path(output_path)
    output.write_text("\n".join(lines), encoding="utf-8")
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
