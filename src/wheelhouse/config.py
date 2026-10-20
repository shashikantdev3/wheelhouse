"""Settings read from the environment and a local .env file.

Secrets are held as SecretStr so they never appear in reprs, logs or error messages.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str | None = None
    wheelhouse_model: str | None = None
    """Model for the crew, for example claude-haiku-5-5 or an OpenRouter model id."""
    wheelhouse_ledger_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("WHEELHOUSE_LEDGER_KEY", "WHEELHOUSE_APPROVAL_KEY"),
    )
    """Secret used to pseudonymise people and agents in the ledger (32+ characters).
    Approvals no longer use a shared secret: each approver has an Ed25519 key.
    WHEELHOUSE_APPROVAL_KEY, the Sprint 1 name, is still read."""

    def providers(self) -> dict[str, bool]:
        """Which model providers are configured. Reports presence only, never values."""
        return {
            "anthropic": bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value()),
            "openrouter": bool(
                self.openrouter_api_key and self.openrouter_api_key.get_secret_value()
            ),
            "ollama": bool(self.ollama_base_url),
        }
