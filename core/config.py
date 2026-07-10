"""Configuration manager for providers and app settings."""

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.models import Provider


_CONFIG_DIR = Path.home() / ".config" / "book-translator"
_PROVIDERS_FILE = _CONFIG_DIR / "providers.json"
_APP_CONFIG_FILE = _CONFIG_DIR / "config.json"

_DEFAULT_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "ollama",
        "name": "Ollama (local)",
        "base_url": "http://localhost:11434",
        "api_key": None,
        "models": {"llama3.1": {"input_cost_per_1k": 0, "output_cost_per_1k": 0}},
        "default_model": "llama3.1",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "models": {"gpt-4o": {"input_cost_per_1k": 0.005, "output_cost_per_1k": 0.015}},
        "default_model": "gpt-4o",
    },
]

_DEFAULT_CONFIG: dict[str, Any] = {
    "temperature": 0.3,
    "top_p": 0.9,
    "max_tokens": 4096,
    "style": "литературный",
    "last_provider_id": "ollama",
    "target_language": "русский",
    "theme": "auto",
    "ui_language": "auto",
}


class ConfigManager:
    """Manages providers and app settings via JSON files in ~/.config/."""

    def __init__(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    def load_providers(self) -> list[Provider]:
        if not _PROVIDERS_FILE.exists():
            self._write_json(_PROVIDERS_FILE, _DEFAULT_PROVIDERS)
        data = self._read_json(_PROVIDERS_FILE, _DEFAULT_PROVIDERS)
        return [Provider(**p) for p in data]

    @staticmethod
    def _serialize(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: ConfigManager._serialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [ConfigManager._serialize(v) for v in obj]
        if hasattr(obj, "__class__") and hasattr(obj, "model_dump"):
            return ConfigManager._serialize(obj.model_dump())
        if isinstance(obj, Decimal):
            return float(obj)
        return obj

    def save_providers(self, providers: list[Provider]) -> None:
        data = self._serialize([p.model_dump(exclude_none=True) for p in providers])
        self._write_json(_PROVIDERS_FILE, data)

    def add_provider(self, provider: Provider) -> list[Provider]:
        providers = self.load_providers()
        providers.append(provider)
        self.save_providers(providers)
        return providers

    def remove_provider(self, provider_id: str) -> list[Provider]:
        providers = self.load_providers()
        providers = [p for p in providers if p.id != provider_id]
        self.save_providers(providers)
        return providers

    def update_provider(self, provider: Provider) -> list[Provider]:
        providers = self.load_providers()
        for i, p in enumerate(providers):
            if p.id == provider.id:
                providers[i] = provider
                break
        self.save_providers(providers)
        return providers

    def get_provider(self, provider_id: str) -> Provider | None:
        providers = self.load_providers()
        for p in providers:
            if p.id == provider_id:
                return p
        return None

    # ------------------------------------------------------------------
    # App config
    # ------------------------------------------------------------------

    def load_app_config(self) -> dict[str, Any]:
        if not _APP_CONFIG_FILE.exists():
            self._write_json(_APP_CONFIG_FILE, _DEFAULT_CONFIG)
            return dict(_DEFAULT_CONFIG)
        data = self._read_json(_APP_CONFIG_FILE, _DEFAULT_CONFIG)
        merged = dict(_DEFAULT_CONFIG)
        merged.update(data)
        return merged

    def save_app_config(self, config: dict[str, Any]) -> None:
        merged = dict(_DEFAULT_CONFIG)
        merged.update(config)
        self._write_json(_APP_CONFIG_FILE, merged)

    # ------------------------------------------------------------------
    # Utils
    # ------------------------------------------------------------------

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            return default

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.chmod(path, 0o600)


# ======================================================================
# Model name normalisation — add provider prefix if missing
# ======================================================================

_URL_TO_PREFIX: dict[str, str] = {
    "openrouter.ai": "openrouter",
    "api.openai.com": "openai",
    "api.anthropic.com": "anthropic",
    "api.deepseek.com": "deepseek",
    "api.groq.com": "groq",
    "api.together.xyz": "together_ai",
    "localhost:11434": "ollama",
}

_KNOWN_PREFIXES = set(_URL_TO_PREFIX.values())


def normalize_model_name(base_url: str, model_name: str) -> str:
    """Ensure a model name has a provider prefix.

    Examples::

        >>> normalize_model_name("https://api.openai.com/v1", "gpt-4o")
        "openai/gpt-4o"
        >>> normalize_model_name("https://openrouter.ai/api/v1", "nvidia/nemotron")
        "openrouter/nvidia/nemotron"
        >>> normalize_model_name("", "openrouter/gpt-4o")
        "openrouter/gpt-4o"
    """
    if not model_name:
        return model_name
    if "/" in model_name:
        prefix = model_name.split("/", 1)[0]
        if prefix in _KNOWN_PREFIXES:
            return model_name
    if base_url:
        for domain, prefix in _URL_TO_PREFIX.items():
            if domain in base_url:
                return f"{prefix}/{model_name}"
    return model_name
