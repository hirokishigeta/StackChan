"""Application configuration.

Values come from environment variables (prefix ``STACKCHAN_``) or defaults.
This module is referenceable from any layer (see CLAUDE.md dependency rules).
No hard-coded URLs / model names live outside of this module.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Runtime settings, overridable via environment variables.

    Example: ``STACKCHAN_DATABASE_URL=sqlite:///./prod.db``.
    """

    model_config = SettingsConfigDict(env_prefix="STACKCHAN_", env_file=".env", extra="ignore")

    app_name: str = "StackChan Backend"
    # SQLite by default; private-network local AI backend (design-spec §10).
    database_url: str = "sqlite:///./stackchan.db"

    # CORS: LAN-only by default (design-spec §13 security).
    cors_allow_origins: list[str] = ["*"]

    # Agent provider selection (resolved via a registry in di_container; the
    # value must match an AgentType, e.g. "OpenAICompatible"). No if-based
    # provider branching (CLAUDE.md / design-spec §13).
    default_agent_type: str = "OpenAICompatible"
    default_agent_model: str = "dummy-model"

    # OpenAI-compatible Gateway (design-spec §11.3). base_url / api_key / model
    # are never hard-coded outside this module (CLAUDE.md).
    agent_base_url: str = "http://localhost:11434/v1"
    agent_api_key: str = ""
    # Per-request timeout in seconds. On timeout the gateway raises AgentError
    # and the API returns a safe fallback so the conversation loop survives.
    agent_request_timeout_s: float = 30.0

    default_speech_provider: str = "dummy"
    default_speech_language: str = "ja"


@lru_cache
def get_settings() -> AppSettings:
    """Return the cached application settings instance."""
    return AppSettings()
