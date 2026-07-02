"""Multi-level structured prompt builder for translation."""

from typing import Literal

Style = Literal["дословный", "литературный", "адаптированный"]

# ---------------------------------------------------------------------------
# Style definitions
# ---------------------------------------------------------------------------

_STYLE_ROLE: dict[Style, str] = {
    "дословный": (
        "You are a precise technical translator. "
        "Your goal is to produce a translation that follows the source text "
        "as closely as possible — preserve word order, structure, and "
        "literal meaning. Do not paraphrase or embellish."
    ),
    "литературный": (
        "You are a professional literary translator. "
        "Your goal is to produce a natural, fluent translation that preserves "
        "the author's voice, tone, and stylistic nuances. "
        "Prefer idiomatic expressions in the target language."
    ),
    "адаптированный": (
        "You are a creative adaptation translator. "
        "Your goal is to adapt the text freely for a modern audience while "
        "preserving the core meaning, plot, and character voice. "
        "You may restructure sentences, modernise archaic language, "
        "and use contemporary idioms."
    ),
}

_STYLE_RULES: dict[Style, str] = {
    "дословный": (
        "- Preserve the original sentence structure as much as possible.\n"
        "- Keep all proper names, dates, and numbers unchanged.\n"
        "- Add brief translator notes in [brackets] only when a term has no direct equivalent."
    ),
    "литературный": (
        "- Maintain the author's style, tone, and register.\n"
        "- Use natural-sounding phrases in the target language.\n"
        "- Preserve metaphors, humour, and cultural references."
    ),
    "адаптированный": (
        "- Adapt the text to sound natural for a modern reader.\n"
        "- You may split or merge sentences for readability.\n"
        "- Replace obscure cultural references with familiar equivalents.\n"
        "- Feel free to modernise archaic expressions."
    ),
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_system_prompt(
    glossary_block: str = "",
    style: Style = "литературный",
    source_language: str = "",
    target_language: str = "",
) -> str:
    """Build the system prompt that defines the translator role, style,
    glossary constraints, output rules, and language pair."""

    parts: list[str] = [
        _STYLE_ROLE[style],
        "",
        f"### Language direction",
        f"Translate from {source_language or 'the source language'} to {target_language or 'the target language'}.",
        "",
        "### Translation rules",
        _STYLE_RULES[style],
    ]

    if glossary_block:
        parts.append("")
        parts.append("### Glossary constraints")
        parts.append(
            "The following terms MUST be translated exactly as specified. "
            "Do NOT deviate from these translations."
        )
        parts.append(glossary_block)

    parts.extend([
        "",
        "### Output rules",
        "- Translate ONLY the paragraph delimited by <translate>...</translate>.",
        "- Do NOT add any commentary, explanations, or notes outside the translation.",
        "- Preserve the original punctuation, line breaks, and paragraph boundaries.",
        "- If a sentence is incomplete, leave it as-is without guessing the ending.",
        "- Output only the translated text, nothing else.",
    ])

    return "\n".join(parts)


def build_user_prompt(original_text: str, context_block: str = "") -> str:
    """Build the user message for a single paragraph.

    ``context_block`` comes from ``context_builder.build_context()``.
    """
    parts: list[str] = []
    if context_block:
        parts.append(context_block)
        parts.append("")
    parts.append(f"<translate>\n{original_text}\n</translate>")
    return "\n".join(parts)


def build_messages(
    original_text: str,
    context_block: str = "",
    glossary_block: str = "",
    style: Style = "литературный",
    source_language: str = "",
    target_language: str = "",
) -> list[dict[str, str]]:
    """Return a complete message list suitable for ``litellm.completion()``.

    Usage::

        messages = build_messages(
            original_text="Hello world",
            context_block=context_builder.build_context(...),
            glossary_block=glossary_manager.format_for_prompt(book_id),
            style="литературный",
            source_language="английский",
            target_language="русский",
        )
        response = await litellm.completion(
            model=model_id,
            messages=messages,
            ...
        )
    """
    return [
        {
            "role": "system",
            "content": build_system_prompt(
                glossary_block,
                style,
                source_language=source_language,
                target_language=target_language,
            ),
        },
        {"role": "user", "content": build_user_prompt(original_text, context_block)},
    ]
