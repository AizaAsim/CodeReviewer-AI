"""GitHub webhook receiver — HMAC verify, enqueue review, fast 200."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, Response

from codereviewer.config import settings
from codereviewer.persistence.models import AsyncSessionLocal
from codereviewer.persistence.repo import create_review_run_if_absent
from codereviewer.webhooks.tasks import run_review

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

_HANDLED_ACTIONS = frozenset({"opened", "synchronize", "reopened"})


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 against the raw request body."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header.removeprefix("sha256=")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected)


def _repo_full_name(payload: dict[str, Any]) -> str | None:
    repo = payload.get("repository") or {}
    full_name = repo.get("full_name")
    if isinstance(full_name, str) and full_name:
        return full_name
    return None


@router.post("/webhooks/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
    # CRITICAL: read raw bytes before any JSON parsing (HMAC must cover exact body).
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not verify_signature(settings.github_webhook_secret, body, signature):
        return Response(status_code=401, content="invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return Response(status_code=200, content="ignored")

    try:
        payload: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400, content="invalid json")

    action = payload.get("action")
    if action not in _HANDLED_ACTIONS:
        return Response(status_code=200, content="ignored")

    sender = payload.get("sender") or {}
    if sender.get("type") == "Bot":
        logger.info("ignoring bot-triggered pull_request event")
        return Response(status_code=200, content="ignored bot")

    pr = payload.get("pull_request") or {}
    repo = _repo_full_name(payload)
    head = (pr.get("head") or {}).get("sha")
    number = pr.get("number")
    if not repo or not head or not isinstance(number, int):
        return Response(status_code=200, content="ignored malformed")

    async with AsyncSessionLocal() as session:
        run_id = await create_review_run_if_absent(
            session, repo=repo, pr_number=number, head_sha=head
        )

    if run_id is None:
        logger.info(
            "duplicate delivery ignored repo=%s pr=%s sha=%s", repo, number, head[:7]
        )
        return Response(status_code=200, content="duplicate")

    background_tasks.add_task(run_review, run_id)
    logger.info("enqueued review run_id=%s repo=%s pr=%s", run_id, repo, number)
    return Response(status_code=200, content="accepted")
