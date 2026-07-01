"""Build context from previously translated paragraphs."""

from core.models import Paragraph


# rough limit to avoid blowing the context window
_MAX_CONTEXT_SYMBOLS = 4000


def build_context(
    paragraphs: list[Paragraph],
    current_index: int,
    n: int = 2,
    max_symbols: int = _MAX_CONTEXT_SYMBOLS,
) -> str:
    """Collect the last *n* translated paragraphs preceding *current_index*
    and format them as a context block for the prompt.

    Only paragraphs with ``status == 'completed'`` and a non-empty
    ``translated_text`` are included.
    """
    before = paragraphs[:current_index]
    done = [p for p in before
            if p.status == "completed" and p.translated_text]

    context: list[str] = []
    total = 0

    for p in reversed(done):
        block = _format_paragraph(p)
        total += len(block)
        if total > max_symbols:
            break
        context.append(block)
        if len(context) >= n:
            break

    context.reverse()
    if not context:
        return ""

    lines = ["<context>", "Below are the previously translated paragraphs:"]
    for block in context:
        lines.append(block)
    lines.append("</context>")
    return "\n".join(lines)


def _format_paragraph(p: Paragraph) -> str:
    title = p.chapter_title or "(no chapter)"
    return f"[{title} §{p.paragraph_index}]\n{p.translated_text}"
