"""Environment-based configuration for the Meridian engine.

All secrets are read from the environment (or a local ``.env`` file). Secret
VALUES are never returned by the status helpers and never logged - only a
boolean "configured" indicator is exposed to the rest of the application.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Dict

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = parent of the ``config`` package directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Best-effort load of a local .env without a hard dependency failure."""
    try:
        from dotenv import load_dotenv

        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except Exception:  # pragma: no cover - dotenv is optional at runtime
        pass


_load_dotenv()


class Settings(BaseSettings):
    """Typed application settings sourced from the environment."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # --- Secrets (never surfaced directly) ---
    brave_search_api_key: str = Field(default="", alias="BRAVE_SEARCH_API_KEY")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    opencorporates_api_key: str = Field(default="", alias="OPENCORPORATES_API_KEY")
    securitytrails_api_key: str = Field(default="", alias="SECURITYTRAILS_API_KEY")
    censys_api_id: str = Field(default="", alias="CENSYS_API_ID")
    censys_api_secret: str = Field(default="", alias="CENSYS_API_SECRET")
    shodan_api_key: str = Field(default="", alias="SHODAN_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # --- SEC EDGAR identification ---
    sec_user_agent: str = Field(default="MeridianVendorIntelligence/1.0", alias="SEC_USER_AGENT")
    sec_contact_email: str = Field(default="", alias="SEC_CONTACT_EMAIL")

    # --- LLM provider abstraction ---
    llm_provider: str = Field(default="none", alias="LLM_PROVIDER")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    # --- Database ---
    db_path: str = Field(default="data/meridian.db", alias="MERIDIAN_DB_PATH")

    # --- Network behaviour / budgets ---
    http_timeout_seconds: float = Field(default=20.0, alias="HTTP_TIMEOUT_SECONDS")
    http_max_retries: int = Field(default=3, alias="HTTP_MAX_RETRIES")
    connector_rate_limit_per_sec: float = Field(default=1.0, alias="CONNECTOR_RATE_LIMIT_PER_SEC")
    investigation_query_budget: int = Field(default=25, alias="INVESTIGATION_QUERY_BUDGET")
    enable_provider_fallback: bool = Field(default=False, alias="ENABLE_PROVIDER_FALLBACK")

    # --- Public web etiquette ---
    public_web_user_agent: str = Field(
        default="MeridianVendorIntelligence/1.0 (+third-party-risk-research)",
        alias="PUBLIC_WEB_USER_AGENT",
    )
    respect_robots_txt: bool = Field(default=True, alias="RESPECT_ROBOTS_TXT")

    # ------------------------------------------------------------------ #
    @property
    def absolute_db_path(self) -> Path:
        p = Path(self.db_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def secret_status(self) -> Dict[str, bool]:
        """Return which secrets are configured, WITHOUT exposing values."""
        return {
            "brave_search": bool(self.brave_search_api_key.strip()),
            "tavily": bool(self.tavily_api_key.strip()),
            "opencorporates": bool(self.opencorporates_api_key.strip()),
            "securitytrails": bool(self.securitytrails_api_key.strip()),
            "censys": bool(self.censys_api_id.strip() and self.censys_api_secret.strip()),
            "shodan": bool(self.shodan_api_key.strip()),
            "openai": bool(self.openai_api_key.strip()),
            "sec_edgar": bool(self.sec_contact_email.strip()),
        }

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider.lower() == "openai" and bool(self.openai_api_key.strip())

    @property
    def any_live_search(self) -> bool:
        return bool(self.brave_search_api_key.strip() or self.tavily_api_key.strip())

    @property
    def offline_mode(self) -> bool:
        """Offline = no live search provider configured."""
        return not self.any_live_search


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests that patch the environment)."""
    get_settings.cache_clear()
