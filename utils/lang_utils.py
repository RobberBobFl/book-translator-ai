"""Language detection utilities for source language auto-detection."""

from langdetect import detect, DetectorFactory, lang_detect_exception

DetectorFactory.seed = 0

_LANG_CODE_TO_NAME: dict[str, str] = {
    "ru": "русский",
    "en": "английский",
}


def detect_source_language(text: str, max_chars: int = 2000) -> str:
    """Detect the language of *text* (first *max_chars* characters).

    Returns a Russian-language name (e.g. ``"английский"``) or
    an empty string if detection fails.
    """
    if not text:
        return ""
    try:
        code = detect(text[:max_chars])
        return _LANG_CODE_TO_NAME.get(code, "")
    except lang_detect_exception.LangDetectException:
        return ""
