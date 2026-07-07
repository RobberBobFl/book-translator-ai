"""Pydantic models for Book Translator."""

from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Literal


class EditRecord(BaseModel):
    """Record of a manual edit made to a paragraph translation."""

    timestamp: str
    old_text: str
    new_text: str


class Paragraph(BaseModel):
    """Single paragraph extracted from a book chapter."""

    id: int = 0
    translation_id: int
    book_id: int
    chapter_title: str
    paragraph_index: int
    original_text: str
    model_id: str
    translated_text: str | None = None
    status: Literal["pending", "translating", "completed", "failed"] = "pending"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    retry_count: int = 0
    error_message: str | None = None
    is_manually_edited: bool = False
    edit_history: list[EditRecord] = Field(default_factory=list)


class Page(BaseModel):
    """A single page (group of paragraphs) to be translated as one unit."""

    id: int = 0
    translation_id: int
    book_id: int
    chapter_title: str
    page_number: int
    original_text: str
    model_id: str = ""
    translated_text: str | None = None
    status: Literal["pending", "translating", "completed", "failed"] = "pending"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    retry_count: int = 0
    error_message: str | None = None
    is_manually_edited: bool = False
    edit_history: list[EditRecord] = Field(default_factory=list)


class Chapter(BaseModel):
    """Chapter of a book containing a list of paragraphs."""

    title: str
    paragraphs: list[Paragraph]


class Book(BaseModel):
    """Complete book with metadata, chapters and translation history."""

    id: int | None = None
    title: str
    source_path: str
    source_format: str
    file_hash: str
    chapters: list[Chapter]
    pages: list[Page] = Field(default_factory=list)
    translations: list["Translation"] = Field(default_factory=list)


class GlossaryEntry(BaseModel):
    """Term and its translation for glossary management."""

    id: int | None = None
    book_id: int
    original_term: str
    translated_term: str | None = None
    is_auto_detected: bool = False
    context: str | None = None


class ModelPricing(BaseModel):
    """Pricing for a specific model in USD per 1K tokens."""

    input_cost_per_1k: Decimal
    output_cost_per_1k: Decimal


class Provider(BaseModel):
    """LLM provider configuration with API details and model pricing."""

    id: str
    name: str
    base_url: str
    api_key: str | None = None
    models: dict[str, ModelPricing]
    default_model: str


class Translation(BaseModel):
    """Represents one complete translation pass of a book."""

    id: int = 0
    book_id: int
    name: str
    model_id: str | None = None
    source_type: Literal["parallel", "imported", "previous"]
    created_at: str
    total_cost: Decimal = Decimal("0")
    total_tokens: int = 0
    mode: Literal["auto", "interactive", "hybrid"] = "auto"


class TranslationJob(BaseModel):
    """Settings for a single translation job (one model)."""

    model_id: str
    temperature: Decimal = Decimal("0.3")
    top_p: Decimal = Decimal("0.9")
    max_tokens: int = 4096
    style: Literal["дословный", "литературный", "адаптированный"] = "литературный"
    mode: Literal["auto", "interactive", "hybrid"] = "auto"
    target_language: str = "русский"


class TranslationResult(BaseModel):
    """Result of a single translation call."""

    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    model_id: str = ""


# Resolve forward references
Book.model_rebuild()
