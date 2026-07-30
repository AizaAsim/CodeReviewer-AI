"""Manual integration test: fetch a real PR's files via the GitHub App.

Requires env:
  TEST_PR_OWNER   e.g. your-github-username
  TEST_PR_REPO    e.g. codereviewer-testbed
  TEST_PR_NUMBER  e.g. 1

Run:
  uv run pytest tests/test_github_client_manual.py -m manual -s
"""

from __future__ import annotations

import os

import pytest

from codereviewer.github_client import GithubClient


@pytest.mark.manual
@pytest.mark.asyncio
async def test_print_pr_files() -> None:
    owner = os.environ.get("TEST_PR_OWNER")
    repo = os.environ.get("TEST_PR_REPO")
    number_raw = os.environ.get("TEST_PR_NUMBER")

    if not owner or not repo or not number_raw:
        pytest.skip(
            "Set TEST_PR_OWNER, TEST_PR_REPO, and TEST_PR_NUMBER to run this test"
        )

    number = int(number_raw)
    client = GithubClient()

    pr = await client.get_pr(owner, repo, number)
    print("\n=== PR metadata ===")
    print(pr.model_dump_json(indent=2))

    files = await client.get_pr_files(owner, repo, number)
    print(f"\n=== {len(files)} file(s) ===")
    for f in files:
        print(f"\n--- {f.filename} ({f.status}) ---")
        print(f"additions={f.additions} deletions={f.deletions} patch={'yes' if f.patch else 'None'}")
        if f.patch:
            print(f.patch[:2000])
            if len(f.patch) > 2000:
                print("... [truncated]")
