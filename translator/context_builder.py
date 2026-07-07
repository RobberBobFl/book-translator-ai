"""Build context from previously translated pages."""

from core.models import Page


# rough limit to avoid blowing the context window
_MAX_CONTEXT_SYMBOLS = 4000


def build_context(
    pages: list[Page],
    current_index: int,
    n: int = 2,
    max_symbols: int = _MAX_CONTEXT_SYMBOLS,
) -> str:
    """Collect the last *n* translated pages preceding *current_index*
    and format them as a context block for the prompt.

    Only pages with ``status == 'completed'`` and a non-empty
    ``translated_text`` are included.
    """
    before = pages[:current_index]
    done = [p for p in before
            if p.status == "completed" and p.translated_text]

    context: list[str] = []
    total = 0

    for p in reversed(done):
        block = _format_page(p)
        total += len(block)
        if total > max_symbols:
            break
        context.append(block)
        if len(context) >= n:
            break

    context.reverse()
    if not context:
        return ""

    lines = ["<context>", "Below are the previously translated pages:"]
    for block in context:
        lines.append(block)
    lines.append("</context>")
    return "\n".join(lines)


def _format_page(p: Page) -> str:
    title = p.chapter_title or f"Page {p.page_number}"
    return f"[{title} стр.{p.page_number}]\n{p.translated_text}"
