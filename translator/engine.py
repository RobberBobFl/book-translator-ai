"""Translation engine wrapping litellm with retry, cost tracking, and chunking."""

import asyncio
import logging
import re
from decimal import Decimal
from typing import Any

import litellm
from litellm import exceptions as litellm_exc

from translator.chunker import split_long_paragraph, merge_chunks
from core.models import TranslationResult
from core.config import normalize_model_name

logger = logging.getLogger(__name__)

# Providers that litellm routes natively (pass model + key through verbatim).
# Anything else (LM Studio, custom OpenAI-compatible local servers, ...) is
# treated as an OpenAI-compatible endpoint.
_NATIVE_CLOUD = {
    "openai", "anthropic", "deepseek", "groq", "together_ai",
    "openrouter", "azure", "gemini", "bedrock", "vertex_ai",
    "xai", "cohere", "mistral",
}
# Always force JSON content-type — some local servers (Ollama) reject the
# request with HTTP 415 otherwise.
_JSON_HEADERS = {"Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class TranslationError(Exception):
    """Raised when translation permanently fails after exhausting retries."""

    def __init__(self, message: str, retry_count: int = 0) -> None:
        self.retry_count = retry_count
        super().__init__(message)


class CriticalTranslationError(Exception):
    """Raised on critical errors (bad model, auth, etc.) that should stop all translation."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class TranslatorEngine:
    """Async wrapper around ``litellm.acompletion()`` with retries,
    cost estimation and automatic chunking for long paragraphs."""

    BACKOFF_SECONDS = (2, 4, 8)  # retry delays

    def __init__(self, config_manager: Any = None) -> None:
        self._client = litellm
        self._config_manager = config_manager  # core.config.ConfigManager

    # ------------------------------------------------------------------
    # Provider lookup
    # ------------------------------------------------------------------

    def _get_provider_for_model(self, model_id: str) -> dict | None:
        """Find provider config by extracting the provider prefix from model_id.

        Returns a dict with keys ``api_key``, ``base_url``, or ``None``.
        """
        if self._config_manager is None:
            return None
        provider_id = model_id.split("/", 1)[0].lower()
        providers = self._config_manager.load_providers()
        for p in providers:
            if p.id == provider_id:
                return {"api_key": p.api_key, "base_url": p.base_url}
        # Fallback: try normalising an unprefixed model name
        if "/" not in model_id:
            for p in providers:
                if model_id in p.models:
                    return {"api_key": p.api_key, "base_url": p.base_url}
                normalised = normalize_model_name(p.base_url, model_id)
                if normalised.startswith(f"{p.id}/"):
                    stripped = normalised.split("/", 1)[1]
                    if stripped != model_id and stripped in p.models:
                        return {"api_key": p.api_key, "base_url": p.base_url}
        return None

    # ------------------------------------------------------------------
    # Call resolution (provider -> litellm args)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_call(
        model_id: str, provider_cfg: dict | None
    ) -> tuple[str, str | None, str | None]:
        """Map a stored ``provider/model`` id to litellm call arguments.

        Returns ``(litellm_model, api_key, api_base)``.

        * Ollama  -> native ``ollama/...`` routing, no key needed.
        * Cloud   -> native routing (openai/anthropic/...), real key.
        * LM Studio / any other local OpenAI-compatible server
                  -> ``openai/<name>`` with a dummy key and ``/v1`` appended
                    to the base URL (litellm adds ``/chat/completions``).
        """
        if not provider_cfg:
            return model_id, None, None

        base = provider_cfg.get("base_url")
        key = provider_cfg.get("api_key")
        prefix = model_id.split("/", 1)[0]

        # Decide by BASE URL, not by the (often mislabeled) model prefix.
        # Real Ollama listens on :11434; everything else local is treated as
        # an OpenAI-compatible server (LM Studio, custom, ...).
        is_ollama = "11434" in (base or "")
        is_local = bool(base) and any(
            h in base for h in ("localhost", "127.0.0.1", "0.0.0.0")
        )
        native_cloud = prefix in _NATIVE_CLOUD and not is_local

        if is_ollama:
            litellm_model = (
                model_id if model_id.startswith("ollama/") else f"ollama/{model_id}"
            )
            return litellm_model, key, base
        if native_cloud:
            return model_id, key, base

        # OpenAI-compatible local / custom server (LM Studio, etc.)
        name = model_id.split("/", 1)[1] if "/" in model_id else model_id
        api_base = (base.rstrip("/") + "/v1") if base else base
        return f"openai/{name}", (key or "not-needed"), api_base

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

    async def validate_model(self, model_id: str) -> tuple[bool, str]:
        """Test model with a minimal prompt.

        Returns ``(True, "")`` on success or ``(False, error_message)``.
        """
        provider_cfg = self._get_provider_for_model(model_id)
        litellm_model, api_key, api_base = self._resolve_call(model_id, provider_cfg)

        logger.info(
            "Validating | model=%s | api_key=%s... | api_base=%s",
            litellm_model,
            api_key[:10] if api_key else "None",
            api_base or "None",
        )

        try:
            kwargs: dict = dict(
                model=litellm_model,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
            )
            if api_key:
                kwargs["api_key"] = api_key
            if api_base:
                kwargs["api_base"] = api_base
            kwargs["extra_headers"] = _JSON_HEADERS
            await self._client.acompletion(**kwargs)
            return True, ""
        except CriticalTranslationError as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)

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
        provider_cfg = self._get_provider_for_model(model_id)
        litellm_model, api_key, api_base = self._resolve_call(model_id, provider_cfg)

        logger.info(
            "Translating | model=%s | api_key=%s... | api_base=%s",
            litellm_model,
            api_key[:10] if api_key else "None",
            api_base or "None",
        )

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                kwargs: dict = dict(
                    model=litellm_model,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                )
                if api_key:
                    kwargs["api_key"] = api_key
                if api_base:
                    kwargs["api_base"] = api_base
                kwargs["extra_headers"] = _JSON_HEADERS
                response = await self._client.acompletion(**kwargs)
                return self._parse_response(response, model_id)

            except litellm_exc.RateLimitError as e:
                last_exc = e
            except litellm_exc.Timeout as e:
                last_exc = e
            except litellm_exc.ServiceUnavailableError as e:
                last_exc = e
            except litellm_exc.APIError as e:
                last_exc = e
            except (
                litellm_exc.BadRequestError,
                litellm_exc.AuthenticationError,
                litellm_exc.PermissionDeniedError,
                litellm_exc.NotFoundError,
            ) as e:
                raise CriticalTranslationError(str(e)) from e
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
