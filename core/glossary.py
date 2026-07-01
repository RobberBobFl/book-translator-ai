"""Glossary management: auto-detect, CRUD, mapping for prompt injection."""

import re
from collections import Counter

from core.models import Book, GlossaryEntry
from state.database import Database


_STOPWORDS: set[str] = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "dare", "ought", "used", "this", "that", "these", "those", "it",
    "its", "he", "she", "they", "we", "you", "i", "me", "him", "her",
    "them", "us", "my", "your", "his", "its", "our", "their", "mine",
    "yours", "hers", "theirs", "ours", "who", "whom", "which", "what",
    "when", "where", "why", "how", "all", "each", "every", "both",
    "few", "many", "much", "some", "any", "no", "none", "not", "only",
    "own", "same", "so", "than", "too", "very", "just", "because",
    "if", "then", "else", "until", "while", "though", "although",
    "after", "before", "between", "under", "over", "above", "below",
    "out", "off", "up", "down", "about", "into", "through", "during",
    "without", "within", "along", "around", "among", "across", "behind",
    "beyond", "upon", "toward", "towards", "via", "per", "but", "nor",
    "yet", "so", "although", "except", "since", "unless", "whereas",
    "chapter", "section", "part", "chapter ", "part ",
    "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "first", "second", "third", "last", "next",
    "previous", "new", "old", "such", "more", "most", "also", "well",
    "back", "still", "even", "another", "other", "over", "under",
}


class GlossaryManager:
    """High-level glossary operations backed by the Database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Auto-detect
    # ------------------------------------------------------------------

    def auto_detect(self, book: Book) -> list[GlossaryEntry]:
        """Scan all paragraphs and auto-detect candidate glossary terms.

        Detects:
        - Words that appear capitalized mid‑sentence (proper nouns)
        - ALL‑CAPS acronyms (>= 2 letters)
        - Words with mixed frequency (CamelCase or repeated terms)

        Returns the list of newly created entries.
        """
        if book.id is None:
            raise ValueError("Book must be saved before auto-detecting glossary")

        all_paras = [p.original_text for ch in book.chapters for p in ch.paragraphs]
        corpus = "\n".join(all_paras)

        candidates: set[str] = set()
        candidates |= self._find_mid_sentence_caps(corpus)
        candidates |= self._find_all_caps(corpus)
        candidates |= self._find_frequent_terms(all_paras)

        # Filter stopwords, numbers-only, short tokens
        filtered: set[str] = set()
        for term in candidates:
            if term.lower() in _STOPWORDS:
                continue
            if len(term) <= 2:
                continue
            if term.isdigit():
                continue
            if not re.search(r"[a-zA-Z]", term):
                continue
            filtered.add(term)

        # Persist
        created: list[GlossaryEntry] = []
        for term in sorted(filtered):
            entry = GlossaryEntry(
                book_id=book.id,
                original_term=term,
                translated_term=None,
                is_auto_detected=True,
                context=self._find_context(term, all_paras),
            )
            created.append(self._db.add_glossary_entry(entry))

        return created

    # ------------------------------------------------------------------
    # CRUD wrappers
    # ------------------------------------------------------------------

    def add_entry(
        self,
        book_id: int,
        original_term: str,
        translated_term: str | None = None,
        is_auto_detected: bool = False,
    ) -> GlossaryEntry:
        entry = GlossaryEntry(
            book_id=book_id,
            original_term=original_term,
            translated_term=translated_term,
            is_auto_detected=is_auto_detected,
        )
        return self._db.add_glossary_entry(entry)

    def get_entries(self, book_id: int) -> list[GlossaryEntry]:
        return self._db.get_glossary(book_id)

    def update_entry(self, entry_id: int, translated_term: str) -> None:
        self._db.update_glossary_entry(entry_id, translated_term)

    def delete_entry(self, entry_id: int) -> None:
        self._db.delete_glossary_entry(entry_id)

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def get_term_mapping(self, book_id: int) -> dict[str, str]:
        """Return {original_term: translated_term} for all entries that
        have a translation. Used to inject into the system prompt."""
        entries = self.get_entries(book_id)
        return {e.original_term: e.translated_term
                for e in entries if e.translated_term}

    def format_for_prompt(self, book_id: int) -> str:
        """Return a formatted table of glossary terms for the system prompt."""
        mapping = self.get_term_mapping(book_id)
        if not mapping:
            return ""
        lines = ["Glossary — strictly use these translations:"]
        for orig, trans in mapping.items():
            lines.append(f"  {orig} → {trans}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_mid_sentence_caps(corpus: str) -> set[str]:
        """Find words capitalised mid-sentence (inside a line, after a
        comma, colon, or after lower-case context)."""

        # Word followed by lower case on the same line → likely proper noun
        candidates: set[str] = set()

        # Words preceded by lower-case word on same line
        pattern = re.compile(r"\b[a-z]+[,;:]?\s+([A-Z][a-zA-Z]{1,})\b")
        candidates.update(pattern.findall(corpus))

        # Words that appear after a backtick or inside quotes
        pattern = re.compile(r"""["'`]([A-Z][a-zA-Z]{1,20})["'`]""")
        candidates.update(pattern.findall(corpus))

        return candidates

    @staticmethod
    def _find_all_caps(corpus: str) -> set[str]:
        """Find ALL CAPS acronyms (2+ letters)."""
        pattern = re.compile(r"\b([A-Z]{2,})\b")
        return set(pattern.findall(corpus))

    @staticmethod
    def _find_frequent_terms(all_paragraphs: list[str]) -> set[str]:
        """Find words that appear more than 3 times across paragraphs."""
        counter: Counter[str] = Counter()
        for para in all_paragraphs:
            words = re.findall(r"[A-Za-z\u00C0-\u024F]+(?:['\u2019][A-Za-z]+)?", para)
            for w in words:
                title = w[0].isupper()
                if title:
                    counter[w] += 1

        threshold = max(3, len(all_paragraphs) // 10)
        return {word for word, count in counter.items()
                if count >= threshold}

    @staticmethod
    def _find_context(term: str, all_paragraphs: list[str]) -> str | None:
        """Find the first paragraph that contains the term."""
        for para in all_paragraphs:
            if term in para:
                if len(para) > 150:
                    idx = para.find(term)
                    start = max(0, idx - 60)
                    end = min(len(para), idx + len(term) + 60)
                    snippet = para[start:end]
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(para):
                        snippet = snippet + "..."
                    return snippet
                return para[:150]
        return None
