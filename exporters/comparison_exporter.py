"""Export a side-by-side comparison of two translations."""

import difflib
from pathlib import Path

from state.database import Database


def export_comparison(
    db: Database,
    translation_a_id: int,
    translation_b_id: int,
    output_path: str | Path,
    format: str = "html",
) -> str:
    """Export a comparison of two translations to HTML.

    Returns the path to the generated file.
    """
    paras_a = db.get_paragraphs(translation_a_id)
    paras_b = db.get_paragraphs(translation_b_id)
    trans_a = db.get_translation(translation_a_id)
    trans_b = db.get_translation(translation_b_id)

    text_a = "\n\n".join(p.translated_text or "" for p in paras_a)
    text_b = "\n\n".join(p.translated_text or "" for p in paras_b)

    lines_a = text_a.splitlines()
    lines_b = text_b.splitlines()

    matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
    diff_lines: list[str] = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        for line in lines_a[i1:i2]:
            if op == "equal":
                diff_lines.append(
                    _diff_line(line, "equal")
                )
            elif op == "replace":
                diff_lines.append(
                    _diff_line(line, "replace")
                )
            elif op == "delete":
                diff_lines.append(
                    _diff_line(line, "delete")
                )
        for line in lines_b[j1:j2]:
            if op == "insert":
                diff_lines.append(
                    f'<tr><td class="ins" colspan="2">{_escape(line)}</td></tr>'
                )

    title_a = trans_a.model_id or "Model A" if trans_a else "Model A"
    title_b = trans_b.model_id or "Model B" if trans_b else "Model B"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Comparison: {title_a} vs {title_b}</title>
<style>
body {{ font-family: sans-serif; margin: 2em; }}
table {{ border-collapse: collapse; width: 100%; }}
th {{ background: #eee; padding: 8px; position: sticky; top: 0; }}
td {{ padding: 6px 10px; vertical-align: top; border-bottom: 1px solid #ddd; }}
tr.diff td {{ background: #ffe0e0; }}
tr.eq td {{ background: #e8ffe8; }}
tr.ins td {{ background: #ffffcc; }}
tr.del td {{ background: #ffcccc; }}
.col-a {{ width: 50%; }}
.col-b {{ width: 50%; }}
</style>
</head>
<body>
<h1>Translation comparison</h1>
<p>{title_a} vs {title_b}</p>
<table>
<thead><tr><th class="col-a">{_escape(title_a)}</th><th class="col-b">{_escape(title_b)}</th></tr></thead>
<tbody>
{''.join(diff_lines)}
</tbody>
</table>
</body>
</html>"""

    output = Path(output_path)
    output.write_text(html, encoding="utf-8")
    return str(output)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _diff_line(text: str, cls: str) -> str:
    escaped = _escape(text)
    return f'<tr class="{cls}"><td class="col-a">{escaped}</td><td class="col-b">{escaped}</td></tr>'
