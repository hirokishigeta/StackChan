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

    # Dummy defaults for the agent / speech layers (replaced in later phases).
    default_agent_type: str = "OpenAICompatible"
    default_agent_model: str = "dummy-model"
    default_speech_provider: str = "dummy"
    default_speech_language: str = "ja"


@lru_cache
def get_settings() -> AppSettings:
    """Return the cached application settings instance."""
    return AppSettings()
