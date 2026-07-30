"""Internal eval endpoints — guarded by EVAL_TOKEN."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from codereviewer.agent.graph import build_eval_graph
from codereviewer.agent.state import TokenBudget
from codereviewer.config import settings

router = APIRouter(prefix="/eval", tags=["eval"])


class EvalReviewRequest(BaseModel):
    repo: str = Field(description="owner/name")
    pr_number: int


class EvalFinding(BaseModel):
    path: str
    line: int
    side: str
    severity: str
    category: str
    confidence: float
    message: str
    suggestion: str | None = None


class EvalReviewResponse(BaseModel):
    decision: str
    files_reviewed: int
    findings: list[EvalFinding]
    filtered: list[EvalFinding]
    tokens_used: int
    duration_ms: int


def _require_eval_token(authorization: str | None) -> None:
    expected = settings.eval_token
    if not expected:
        raise HTTPException(status_code=503, detail="EVAL_TOKEN is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid token")


@router.post("/review", response_model=EvalReviewResponse)
async def eval_review(
    payload: EvalReviewRequest,
    authorization: str | None = Header(default=None),
) -> EvalReviewResponse:
    """Run the review graph synchronously for one PR (no GitHub posting)."""
    _require_eval_token(authorization)
    started = time.perf_counter()

    graph = build_eval_graph()
    state: dict[str, Any] = await graph.ainvoke(
        {
            "run_id": uuid.uuid4(),
            "repo": payload.repo,
            "pr_number": payload.pr_number,
            "pr": None,
            "raw_files": [],
            "files": [],
            "current_file": None,
            "classifications": {},
            "findings": [],
            "filtered": [],
            "decision": "skip",
            "posted": [],
            "budget": TokenBudget(),
            "token_events": [],
        }
    )

    duration_ms = int((time.perf_counter() - started) * 1000)

    def _map(items: list) -> list[EvalFinding]:
        return [
            EvalFinding(
                path=item.path,
                line=item.line,
                side=item.side,
                severity=item.severity,
                category=item.category,
                confidence=item.confidence,
                message=item.message,
                suggestion=item.suggestion,
            )
            for item in items
        ]

    return EvalReviewResponse(
        decision=state["decision"],
        files_reviewed=len(state["files"]),
        findings=_map(state["findings"]),
        filtered=_map(state["filtered"]),
        tokens_used=state["budget"].spent,
        duration_ms=duration_ms,
    )
