"""Webhook HMAC + idempotency tests (uses local Postgres)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from codereviewer.config import settings
from codereviewer.main import app
from codereviewer.persistence.models import AsyncSessionLocal, ReviewRun

webhook_router_module = importlib.import_module("codereviewer.webhooks.router")

_TEST_REPO = "AizaAsim/codereviewer-testbed"


def _sign(body: bytes, secret: str | None = None) -> str:
    key = (secret or settings.github_webhook_secret).encode("utf-8")
    digest = hmac.new(key, body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _pr_payload(
    *,
    action: str = "opened",
    repo: str = _TEST_REPO,
    number: int = 1,
    head_sha: str = "abc123deadbeef",
    sender_type: str = "User",
) -> dict:
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "number": number,
            "head": {"sha": head_sha},
            "user": {"login": "AizaAsim", "type": "User"},
        },
        "repository": {"full_name": repo},
        "sender": {"login": "AizaAsim", "type": sender_type},
    }


async def _delete_test_runs() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ReviewRun).where(ReviewRun.repo == _TEST_REPO))
        await session.commit()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def stub_background_review(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhook_router_module, "run_review", AsyncMock())


@pytest.fixture
def clean_runs():
    asyncio.run(_delete_test_runs())
    yield
    asyncio.run(_delete_test_runs())


def test_valid_signature_accepted(client: TestClient, clean_runs) -> None:
    payload = _pr_payload(head_sha=f"valid-{uuid.uuid4().hex}")
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert response.status_code == 200
    assert response.text == "accepted"


def test_tampered_body_rejected(client: TestClient) -> None:
    payload = _pr_payload()
    body = json.dumps(payload).encode("utf-8")
    tampered = body + b" "
    response = client.post(
        "/webhooks/github",
        content=tampered,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert response.status_code == 401


def test_missing_signature_rejected(client: TestClient) -> None:
    body = json.dumps(_pr_payload()).encode("utf-8")
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
        },
    )
    assert response.status_code == 401


def test_duplicate_delivery_is_noop(client: TestClient, clean_runs) -> None:
    head_sha = f"dup-{uuid.uuid4().hex}"
    payload = _pr_payload(head_sha=head_sha)
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": _sign(body),
    }

    first = client.post("/webhooks/github", content=body, headers=headers)
    second = client.post("/webhooks/github", content=body, headers=headers)

    assert first.status_code == 200
    assert first.text == "accepted"
    assert second.status_code == 200
    assert second.text == "duplicate"


def test_duplicate_leaves_single_row(client: TestClient, clean_runs) -> None:
    head_sha = f"row-{uuid.uuid4().hex}"
    payload = _pr_payload(head_sha=head_sha)
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": _sign(body),
    }
    client.post("/webhooks/github", content=body, headers=headers)
    client.post("/webhooks/github", content=body, headers=headers)

    async def _count() -> list[ReviewRun]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ReviewRun).where(
                    ReviewRun.repo == _TEST_REPO,
                    ReviewRun.head_sha == head_sha,
                )
            )
            return list(result.scalars().all())

    rows = asyncio.run(_count())
    assert len(rows) == 1
    assert rows[0].status in {"received", "reviewing"}


def test_bot_sender_ignored(client: TestClient, clean_runs) -> None:
    payload = _pr_payload(sender_type="Bot", head_sha=f"bot-{uuid.uuid4().hex}")
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _sign(body),
        },
    )
    assert response.status_code == 200
    assert response.text == "ignored bot"
