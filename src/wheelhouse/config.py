"""Settings read from the environment and a local .env file.

Secrets are held as SecretStr so they never appear in reprs, logs or error messages.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str | None = None
    wheelhouse_approval_key: SecretStr | None = None
    """Secret used to sign approvals. At least 32 bytes; generate with
    `python -c "import secrets; print(secrets.token_hex(32))"`."""

    def providers(self) -> dict[str, bool]:
        """Which model providers are configured. Reports presence only, never values."""
        return {
            "anthropic": bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value()),
            "openrouter": bool(
                self.openrouter_api_key and self.openrouter_api_key.get_secret_value()
            ),
            "ollama": bool(self.ollama_base_url),
        }
