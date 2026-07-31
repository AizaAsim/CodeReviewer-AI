from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from codereviewer.agent.nodes.post_review import build_summary_body, format_comment_body
from codereviewer.agent.state import Finding, TokenBudget
from codereviewer.diff_engine.models import DiffFile
from codereviewer.github_client.client import _rejected_comment_indexes
from codereviewer.github_client.models import PRMetadata


def test_format_comment_body_with_suggestion() -> None:
    finding = Finding(
        path="app/users.py",
        line=6,
        side="RIGHT",
        severity="critical",
        category="security",
        message="SQL injection via f-string",
        confidence=0.95,
        suggestion='query = "SELECT * FROM users WHERE name = %s"',
    )
    body = format_comment_body(finding)
    assert "🔴 **security**" in body
    assert "SQL injection via f-string" in body
    assert "```suggestion" in body
    assert "WHERE name = %s" in body


def test_build_summary_approve_note() -> None:
    state = {
        "decision": "approve_note",
        "files": [DiffFile(path="a.py", language="python", status="modified", hunks=[])],
        "filtered": [],
        "budget": TokenBudget(),
    }
    assert "no significant issues found" in build_summary_body(state)  # type: ignore[arg-type]


def test_build_summary_comment_counts() -> None:
    state = {
        "decision": "comment",
        "files": [DiffFile(path="a.py", language="python", status="modified", hunks=[])],
        "filtered": [
            Finding(
                path="a.py",
                line=1,
                severity="critical",
                category="security",
                message="x",
                confidence=0.9,
            ),
            Finding(
                path="a.py",
                line=2,
                severity="warning",
                category="logic",
                message="y",
                confidence=0.9,
            ),
        ],
        "budget": TokenBudget(),
    }
    body = build_summary_body(state)  # type: ignore[arg-type]
    assert "1 critical" in body
    assert "1 warning" in body


def test_rejected_comment_indexes_from_error_payload() -> None:
    response = SimpleNamespace(
        json=lambda: {
            "message": "Validation Failed",
            "errors": [
                {
                    "resource": "PullRequestReview",
                    "field": "comments",
                    "code": "custom",
                    "message": "comments[1].line must be part of the diff",
                }
            ],
        }
    )
    exc = SimpleNamespace(response=response)
    assert _rejected_comment_indexes(exc, 3) == {1}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_post_review_node_approve_note(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    post_review_mod = importlib.import_module("codereviewer.agent.nodes.post_review")

    mock_client = AsyncMock()
    mock_client.post_review = AsyncMock(
        return_value=SimpleNamespace(posted=[], rejected=[])
    )
    monkeypatch.setattr(
        post_review_mod, "GithubClient", lambda **_kwargs: mock_client
    )

    state = {
        "run_id": None,
        "repo": "AizaAsim/codereviewer-testbed",
        "pr_number": 6,
        "pr": PRMetadata(
            owner="AizaAsim",
            repo="codereviewer-testbed",
            number=6,
            title="clean",
            author="AizaAsim",
            base_sha="a",
            head_sha="b",
            changed_files=1,
            additions=1,
            deletions=0,
        ),
        "raw_files": [],
        "files": [DiffFile(path="app/mathutil.py", language="python", status="added", hunks=[])],
        "current_file": None,
        "classifications": {},
        "findings": [],
        "filtered": [],
        "decision": "approve_note",
        "posted": [],
        "budget": TokenBudget(),
        "token_events": [],
    }
    result = await post_review_mod.post_review(state)  # type: ignore[arg-type]
    assert result["posted"] == []
    mock_client.post_review.assert_awaited_once()
    kwargs = mock_client.post_review.await_args.kwargs
    assert kwargs["comments"] == []
    assert "no significant issues found" in kwargs["body"]
