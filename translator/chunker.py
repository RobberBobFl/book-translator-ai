"""Split long paragraphs into sentence-aligned chunks and merge them back."""

import re

# Rough heuristic: ~4 chars per token for mixed EN/RU text
_CHARS_PER_TOKEN = 4
_DEFAULT_MAX_TOKENS = 4000
_DEFAULT_MAX_CHARS: int = _DEFAULT_MAX_TOKENS * _CHARS_PER_TOKEN

# Abbreviations that should not trigger a sentence split
_ABBREVIATIONS = (
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs",
    "inc", "ltd", "co", "corp", "dept", "apt", "etc", "est",
    "approx", "de", "dept", "e.g", "i.e", "al", "fig",
    "p", "pp", "ch", "vol", "no", "ex", "rev", "ed",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "oct", "nov", "dec",
)

# Build regex pattern for abbreviations (protect ALL occurrences)
_ABBR_PATTERN = re.compile(
    r"\b(?:" + "|".join(_ABBREVIATIONS) + r")\.(?=\s)",
    re.IGNORECASE,
)

# Multi-dot markers like ellipsis, "!..", "?.."
_ELLIPSIS_PATTERN = re.compile(r"[.!?]\.{2,}")

# Number patterns: decimals 3.14, ordinals 1st, dates 12.05.2024
_NUMBER_DOT = re.compile(r"\b(\d+\.\d+)\b")

# Initials: J. K. Rowling, W. Churchill
_INITIALS = re.compile(r"\b([A-Z]\.\s)(?=[A-Z])")

# Sentence split pattern: . ! ? followed by whitespace + uppercase/quote/bullet/dash
_SENTENCE_SPLIT = re.compile(
    r"""(?<=[.!?])\s+(?=["''«»A-ZА-Я0-9(\-—])"""
)


def split_long_paragraph(
    text: str,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> list[str]:
    """Split a paragraph into sentence-aligned chunks.

    Each chunk should stay under *max_tokens* tokens (estimated as
    ``len(text) // _CHARS_PER_TOKEN``).

    Returns a list of text chunks.
    """
    max_chars = max_tokens * _CHARS_PER_TOKEN

    if len(text) <= max_chars or not text.strip():
        return [text]

    sentences = _split_sentences(text)
    return _group_sentences(sentences, max_chars)


def merge_chunks(chunks: list[str]) -> str:
    """Join translated chunks back into a single paragraph."""
    return " ".join(chunks)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Split text into individual sentences, respecting abbreviations."""

    def protect_dot(m: re.Match) -> str:
        return m.group(0).replace(".", "<DOT>")

    # Protect abbreviations (any letter. followed by whitespace)
    text = _ABBR_PATTERN.sub(protect_dot, text)
    # Protect ellipsis
    text = _ELLIPSIS_PATTERN.sub(protect_dot, text)
    # Protect decimal numbers
    text = _NUMBER_DOT.sub(protect_dot, text)
    # Protect initials
    text = _INITIALS.sub(protect_dot, text)

    # Split on sentence boundaries
    raw = _SENTENCE_SPLIT.split(text)

    # Restore dots
    result = [s.replace("<DOT>", ".") for s in raw]
    return [s.strip() for s in result if s.strip()]


def _group_sentences(sentences: list[str], max_chars: int) -> list[str]:
    """Group sentences into chunks respecting the char limit."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent) + 1  # +1 for the space

        if current_len + sent_len > max_chars and current:
            chunks.append(" ".join(current))
            current = []
            current_len = 0

        current.append(sent)
        current_len += sent_len

    if current:
        chunks.append(" ".join(current))

    return chunks
