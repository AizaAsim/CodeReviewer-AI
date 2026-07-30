from __future__ import annotations

from typing import Any

from codereviewer.agent.state import ReviewState, TokenBudget
from codereviewer.github_client import GithubClient


async def fetch_pr_context(state: ReviewState) -> dict[str, Any]:
    owner, repo_name = state["repo"].split("/", 1)
    client = GithubClient()
    pr = await client.get_pr(owner, repo_name, state["pr_number"])
    raw_files = await client.get_pr_files(owner, repo_name, state["pr_number"])

    # Do not return reducer fields (findings/token_events) — later nodes that
    # spread full state into operator.add channels would duplicate them.
    return {
        "pr": pr,
        "raw_files": raw_files,
        "files": [],
        "current_file": None,
        "classifications": {},
        "filtered": [],
        "decision": "skip",
        "posted": [],
        "budget": TokenBudget(),
    }
