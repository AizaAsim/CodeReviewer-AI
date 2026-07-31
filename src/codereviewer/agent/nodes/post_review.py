from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from codereviewer.agent.state import Finding, PostedComment, ReviewState
from codereviewer.github_client import GithubClient
from codereviewer.github_client.models import ReviewComment

logger = logging.getLogger(__name__)

_SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning": "🟡",
    "nit": "🔵",
}


def format_comment_body(finding: Finding) -> str:
    emoji = _SEVERITY_EMOJI.get(finding.severity, "⚪")
    parts = [f"{emoji} **{finding.category}** — {finding.message}"]
    if finding.suggestion:
        parts.append("")
        parts.append("```suggestion")
        parts.append(finding.suggestion.rstrip("\n"))
        parts.append("```")
    return "\n".join(parts)


def build_summary_body(state: ReviewState) -> str:
    counts = Counter(finding.severity for finding in state["filtered"])
    files_n = len(state["files"])
    if state["decision"] == "approve_note":
        return f"Reviewed {files_n} file(s) — no significant issues found."

    bits: list[str] = []
    for severity in ("critical", "warning", "nit"):
        if counts[severity]:
            bits.append(f"{counts[severity]} {severity}")
    summary = ", ".join(bits) if bits else "no gated findings"
    return (
        f"Reviewed {files_n} file(s). Findings to discuss: {summary}.\n\n"
        "Inline comments cover the highest-confidence issues only."
    )


async def post_review(state: ReviewState) -> dict[str, Any]:
    if state["decision"] == "skip":
        return {"posted": []}

    pr = state["pr"]
    if pr is None:
        logger.error("post_review: missing PR metadata")
        return {"posted": []}

    owner, repo_name = state["repo"].split("/", 1)
    client = GithubClient(installation_id=state.get("installation_id"))
    body = build_summary_body(state)

    comments: list[ReviewComment] = []
    if state["decision"] == "comment":
        for finding in state["filtered"]:
            comments.append(
                {
                    "path": finding.path,
                    "line": finding.line,
                    "side": finding.side,
                    "body": format_comment_body(finding),
                }
            )

    result = await client.post_review(
        owner=owner,
        repo=repo_name,
        number=state["pr_number"],
        commit_id=pr.head_sha,
        body=body,
        comments=comments,
    )

    if result.rejected:
        logger.warning(
            "Dropped %s invalid review comment(s) for %s#%s",
            len(result.rejected),
            state["repo"],
            state["pr_number"],
        )

    posted = [
        PostedComment(
            path=comment["path"],
            line=comment["line"],
            side=comment["side"],
            body=comment["body"],
        )
        for comment in result.posted
    ]
    return {"posted": posted}
