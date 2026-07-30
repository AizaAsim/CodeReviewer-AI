from __future__ import annotations

import base64
from pathlib import Path

from codereviewer.config import Settings


def test_load_private_key_from_file(tmp_path: Path, monkeypatch) -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nABC\n-----END RSA PRIVATE KEY-----\n"
    key_file = tmp_path / "key.pem"
    key_file.write_text(pem, encoding="utf-8")

    settings = Settings(
        github_app_id="1",
        github_app_private_key_path=str(key_file),
        github_webhook_secret="s",
        github_installation_id="2",
        groq_api_key="g",
    )
    assert settings.load_github_app_private_key() == pem


def test_load_private_key_prefers_env_over_path() -> None:
    settings = Settings(
        github_app_id="1",
        github_app_private_key_path="/missing.pem",
        github_app_private_key="-----BEGIN RSA PRIVATE KEY-----\\nABC\\n-----END RSA PRIVATE KEY-----",
        github_webhook_secret="s",
        github_installation_id="2",
        groq_api_key="g",
    )
    key = settings.load_github_app_private_key()
    assert "BEGIN RSA PRIVATE KEY" in key
    assert "\\n" not in key
    assert "\nABC\n" in key


def test_load_private_key_base64() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nABC\n-----END RSA PRIVATE KEY-----\n"
    encoded = base64.b64encode(pem.encode("utf-8")).decode("ascii")
    settings = Settings(
        github_app_id="1",
        github_app_private_key_path="/missing.pem",
        github_app_private_key_base64=encoded,
        github_webhook_secret="s",
        github_installation_id="2",
        groq_api_key="g",
    )
    assert settings.load_github_app_private_key().strip() == pem.strip()


def test_normalize_postgres_url() -> None:
    settings = Settings(
        github_app_id="1",
        github_app_private_key="k",
        github_webhook_secret="s",
        github_installation_id="2",
        groq_api_key="g",
        database_url="postgresql://user:pass@host:5432/db",
    )
    assert settings.database_url.startswith("postgresql+psycopg://")
