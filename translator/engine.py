"""Translation engine wrapping litellm with retry, cost tracking, and chunking."""

import asyncio
import re
from decimal import Decimal

import litellm
from litellm import exceptions as litellm_exc

from translator.chunker import split_long_paragraph, merge_chunks
from core.models import TranslationResult


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class TranslationError(Exception):
    """Raised when translation permanently fails after exhausting retries."""

    def __init__(self, message: str, retry_count: int = 0) -> None:
        self.retry_count = retry_count
        super().__init__(message)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class TranslatorEngine:
    """Async wrapper around ``litellm.acompletion()`` with retries,
    cost estimation and automatic chunking for long paragraphs."""

    BACKOFF_SECONDS = (2, 4, 8)  # retry delays

    def __init__(self) -> None:
        self._client = litellm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def translate(
        self,
        messages: list[dict],
        model_id: str,
        temperature: float = 0.3,
        top_p: float = 0.9,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ) -> TranslationResult:
        """Translate a single paragraph (possibly with context/glossary).

        If the text inside ``<translate>`` exceeds ~4000 tokens, it will
        automatically be split into chunks, translated individually (with
        the same context), and merged back.
        """
        user_text = self._extract_user_text(messages)
        translate_text = self._extract_translate_content(user_text)

        if self._needs_chunking(translate_text):
            return await self._translate_chunked(
                messages, model_id, temperature, top_p, max_tokens, max_retries,
            )

        return await self._translate_once(
            messages, model_id, temperature, top_p, max_tokens, max_retries,
        )

    # ------------------------------------------------------------------
    # Cost helper (public for GUI usage)
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_cost(model_id: str, tokens_in: int, tokens_out: int) -> Decimal:
        """Return estimated cost in USD for the given token counts.

        Uses ``litellm.model_cost`` for known models.  Returns ``Decimal(0)``
        for local models (Ollama, etc.) or unknown models.
        """
        cost_info = litellm.model_cost.get(model_id)
        if cost_info is not None:
            input_price = Decimal(str(cost_info.get("input_cost_per_token", 0)))
            output_price = Decimal(str(cost_info.get("output_cost_per_token", 0)))
            return tokens_in * input_price + tokens_out * output_price

        # Try provider-based fallback (e.g. "ollama/llama3" → ollama = free)
        provider = model_id.split("/", 1)[0].lower()
        if provider in ("ollama", "local"):
            return Decimal("0")

        # Unknown model — estimate 0 (user must configure manually)
        return Decimal("0")

    @staticmethod
    def get_max_tokens_for_model(model_id: str) -> int:
        """Return the context window size for a model (or 4096 as default)."""
        cost_info = litellm.model_cost.get(model_id)
        if cost_info is not None:
            return int(cost_info.get("max_tokens", 4096))
        return 4096

    # ------------------------------------------------------------------
    # Internal: single shot + retry
    # ------------------------------------------------------------------

    async def _translate_once(
        self,
        messages: list[dict],
        model_id: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        max_retries: int,
    ) -> TranslationResult:
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = await self._client.acompletion(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                )
                return self._parse_response(response, model_id)

            except litellm_exc.RateLimitError as e:
                last_exc = e
            except litellm_exc.Timeout as e:
                last_exc = e
            except litellm_exc.ServiceUnavailableError as e:
                last_exc = e
            except litellm_exc.APIError as e:
                last_exc = e
            except Exception as e:
                # Unexpected errors — don't retry
                raise TranslationError(str(e), retry_count=0) from e

            if attempt < max_retries:
                delay = self.BACKOFF_SECONDS[min(attempt, len(self.BACKOFF_SECONDS) - 1)]
                await asyncio.sleep(delay)

        raise TranslationError(
            str(last_exc) if last_exc else "Unknown error",
            retry_count=max_retries,
        )

    # ------------------------------------------------------------------
    # Internal: chunking for long paragraphs
    # ------------------------------------------------------------------

    async def _translate_chunked(
        self,
        messages: list[dict],
        model_id: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        max_retries: int,
    ) -> TranslationResult:
        user_text = self._extract_user_text(messages)
        prefix, translate_text, suffix = self._split_translate_block(user_text)
        chunks = split_long_paragraph(translate_text)

        if len(chunks) <= 1:
            # After splitting it's still one piece → just translate directly
            return await self._translate_once(
                messages, model_id, temperature, top_p, max_tokens, max_retries,
            )

        translated_chunks: list[str] = []
        total_in = 0
        total_out = 0

        for chunk in chunks:
            chunk_msg = self._rebuild_message(messages, prefix, chunk, suffix)
            result = await self._translate_once(
                chunk_msg, model_id, temperature, top_p, max_tokens, max_retries,
            )
            translated_chunks.append(result.text)
            total_in += result.tokens_in
            total_out += result.tokens_out

        merged = merge_chunks(translated_chunks)
        cost = self.estimate_cost(model_id, total_in, total_out)
        return TranslationResult(
            text=merged,
            tokens_in=total_in,
            tokens_out=total_out,
            cost_usd=cost,
            model_id=model_id,
        )

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(response, model_id: str) -> TranslationResult:
        """Extract text and token counts from the litellm response."""
        choice = response.choices[0]
        text: str = choice.message.content or ""

        usage = getattr(response, "usage", None)
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0

        cost = TranslatorEngine.estimate_cost(model_id, tokens_in, tokens_out)

        return TranslationResult(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            model_id=model_id,
        )

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_user_text(messages: list[dict]) -> str:
        """Return the ``content`` of the last ``user`` message."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    @staticmethod
    def _extract_translate_content(user_text: str) -> str:
        """Return the text inside the ``<translate>`` block."""
        m = re.search(r"<translate>\n?(.*?)\n?</translate>", user_text, re.DOTALL)
        return m.group(1).strip() if m else user_text.strip()

    @staticmethod
    def _split_translate_block(user_text: str) -> tuple[str, str, str]:
        """Split user text into (prefix, translate_body, suffix).

        ``prefix`` and ``suffix`` are everything before / after the
        ``<translate>`` block (context, instructions, etc.).
        """
        m = re.search(r"(<translate>\n?)(.*?)(\n?</translate>)", user_text, re.DOTALL)
        if not m:
            return (user_text, "", "")
        prefix = user_text[: m.start(1)]
        body = m.group(2)
        suffix = user_text[m.end(3) :]
        return (prefix, body, suffix)

    @staticmethod
    def _rebuild_message(
        messages: list[dict],
        prefix: str,
        chunk: str,
        suffix: str,
    ) -> list[dict]:
        """Rebuild the message list with the original prefix/suffix but a
        different chunk as the translate content."""
        new_messages = []
        for msg in messages:
            if msg.get("role") == "user":
                content = prefix + f"<translate>\n{chunk}\n</translate>" + suffix
                new_messages.append({"role": "user", "content": content})
            else:
                new_messages.append(dict(msg))
        return new_messages

    @staticmethod
    def _needs_chunking(translate_text: str) -> bool:
        """Heuristic: flag text that probably exceeds the safe token limit."""
        if not translate_text:
            return False
        # ~4 chars per token, trigger at ~3500 to leave room for context
        return len(translate_text) > 3500 * 4
