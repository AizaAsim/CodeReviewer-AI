from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_app_id: str
    github_app_private_key_path: str = "./github-app.private-key.pem"
    # Prefer these in production (Render/etc). Plain PEM or base64 of PEM.
    github_app_private_key: str | None = None
    github_app_private_key_base64: str | None = None
    github_webhook_secret: str
    github_installation_id: str
    groq_api_key: str
    database_url: str = (
        "postgresql+psycopg://reviewer:reviewer@localhost:5434/reviewer"
    )
    log_level: str = "INFO"
    eval_token: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        """Supabase/Render often hand out postgresql:// — force the async psycopg driver."""
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if isinstance(value, str) and value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        return value

    @property
    def db_connect_args(self) -> dict[str, object]:
        """Supabase's transaction pooler (port 6543) rejects prepared statements."""
        if "pooler.supabase.com" in self.database_url and ":6543" in self.database_url:
            return {"prepare_threshold": None}
        return {}

    @model_validator(mode="after")
    def resolve_private_key(self) -> Settings:
        # Normalize escaped newlines from env paste into real PEM body.
        if self.github_app_private_key:
            self.github_app_private_key = self.github_app_private_key.replace(
                "\\n", "\n"
            ).strip()
        return self

    def load_github_app_private_key(self) -> str:
        """Return PEM text: base64 env → raw env → file path."""
        if self.github_app_private_key_base64:
            decoded = base64.b64decode(self.github_app_private_key_base64).decode(
                "utf-8"
            )
            return decoded.replace("\\n", "\n").strip() + (
                "" if decoded.strip().endswith("\n") else "\n"
            )

        if self.github_app_private_key:
            key = self.github_app_private_key.strip()
            return key if key.endswith("\n") else key + "\n"

        path = Path(self.github_app_private_key_path)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(
                "GitHub App private key not found. Set GITHUB_APP_PRIVATE_KEY, "
                "GITHUB_APP_PRIVATE_KEY_BASE64, or GITHUB_APP_PRIVATE_KEY_PATH."
            ) from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
