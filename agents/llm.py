"""Provider-agnostic LLM abstraction.

Core business logic never imports a specific vendor SDK directly; it talks to
``LLMClient``. When no provider is configured, ``available`` is False and
callers fall back to deterministic processing. The LLM may only PROPOSE
classifications - deterministic layers compute every final score.
"""
from __future__ import annotations

from typing import Optional

from config.logging_config import get_logger
from config.settings import Settings, get_settings

log = get_logger("llm")


class LLMClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    @property
    def available(self) -> bool:
        return self.settings.llm_enabled

    @property
    def provider(self) -> str:
        return self.settings.llm_provider

    def complete(self, prompt: str, system: Optional[str] = None, max_tokens: int = 600) -> Optional[str]:
        """Return a completion string, or None when unavailable / on error."""
        if not self.available:
            return None
        provider = self.settings.llm_provider.lower()
        try:
            if provider == "openai":
                return self._openai_complete(prompt, system, max_tokens)
        except Exception as exc:  # pragma: no cover - network path
            log.warning("llm completion failed provider=%s error=%s", provider, type(exc).__name__)
            return None
        return None

    # ------------------------------------------------------------------ #
    def _openai_complete(self, prompt: str, system: Optional[str], max_tokens: int) -> Optional[str]:
        try:
            from openai import OpenAI
        except ImportError:
            log.warning("openai package not installed; LLM features disabled")
            return None
        client = OpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url or None,
        )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=self.settings.openai_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return resp.choices[0].message.content
