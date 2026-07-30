"""GitHub App client using githubkit installation auth."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from githubkit import AppInstallationAuthStrategy, GitHub
from githubkit.exception import GitHubException, RequestFailed
from githubkit.utils import UNSET

from codereviewer.config import settings
from codereviewer.github_client.errors import GithubError
from codereviewer.github_client.models import (
    PostReviewResult,
    PRMetadata,
    RawFile,
    ReviewComment,
)

logger = logging.getLogger(__name__)

_LINE_ERROR_RE = re.compile(
    r"comments?\[(\d+)\].*line|line.*comments?\[(\d+)\]|comments\.(\d+)\.line",
    re.IGNORECASE,
)


class GithubClient:
    """Authenticated GitHub App client scoped to the configured installation."""

    def __init__(
        self,
        *,
        app_id: str | None = None,
        private_key: str | None = None,
        private_key_path: str | None = None,
        installation_id: str | int | None = None,
    ) -> None:
        resolved_app_id = app_id or settings.github_app_id
        resolved_installation_id = int(
            installation_id or settings.github_installation_id
        )

        if private_key is not None:
            pem = private_key
        elif private_key_path is not None:
            try:
                pem = Path(private_key_path).read_text(encoding="utf-8")
            except OSError as exc:
                raise GithubError(
                    f"Failed to read private key at {private_key_path}"
                ) from exc
        else:
            try:
                pem = settings.load_github_app_private_key()
            except RuntimeError as exc:
                raise GithubError(str(exc)) from exc

        auth = AppInstallationAuthStrategy(
            resolved_app_id,
            pem,
            resolved_installation_id,
        )
        self._gh = GitHub(auth)

    async def get_pr(self, owner: str, repo: str, number: int) -> PRMetadata:
        try:
            response = await self._gh.rest.pulls.async_get(
                owner=owner, repo=repo, pull_number=number
            )
        except RequestFailed as exc:
            raise GithubError(
                f"Failed to fetch PR {owner}/{repo}#{number}",
                status=exc.response.status_code,
            ) from exc
        except GitHubException as exc:
            raise GithubError(f"Failed to fetch PR {owner}/{repo}#{number}") from exc

        pr = response.parsed_data
        return PRMetadata(
            owner=owner,
            repo=repo,
            number=pr.number,
            title=pr.title,
            author=pr.user.login,
            base_sha=pr.base.sha,
            head_sha=pr.head.sha,
            changed_files=pr.changed_files,
            additions=pr.additions,
            deletions=pr.deletions,
        )

    async def get_pr_files(self, owner: str, repo: str, number: int) -> list[RawFile]:
        files: list[RawFile] = []
        page = 1
        per_page = 100

        while True:
            try:
                response = await self._gh.rest.pulls.async_list_files(
                    owner=owner,
                    repo=repo,
                    pull_number=number,
                    per_page=per_page,
                    page=page,
                )
            except RequestFailed as exc:
                raise GithubError(
                    f"Failed to fetch files for PR {owner}/{repo}#{number}",
                    status=exc.response.status_code,
                ) from exc
            except GitHubException as exc:
                raise GithubError(
                    f"Failed to fetch files for PR {owner}/{repo}#{number}"
                ) from exc

            batch = response.parsed_data
            for entry in batch:
                patch = entry.patch
                if patch is UNSET or patch is None:
                    patch_value: str | None = None
                else:
                    patch_value = str(patch)

                previous = entry.previous_filename
                if previous is UNSET or previous is None:
                    previous_value: str | None = None
                else:
                    previous_value = str(previous)

                files.append(
                    RawFile(
                        filename=entry.filename,
                        status=entry.status,
                        patch=patch_value,
                        additions=entry.additions,
                        deletions=entry.deletions,
                        previous_filename=previous_value,
                    )
                )

            if len(batch) < per_page:
                break
            page += 1

        return files

    async def post_review(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        body: str,
        comments: list[ReviewComment],
    ) -> PostReviewResult:
        """Create one PR review (COMMENT event). Retry without invalid line comments on 422."""
        remaining = list(comments)
        rejected: list[ReviewComment] = []

        while True:
            try:
                await self._create_review(
                    owner=owner,
                    repo=repo,
                    number=number,
                    commit_id=commit_id,
                    body=body,
                    comments=remaining,
                )
                return PostReviewResult(posted=remaining, rejected=rejected)
            except RequestFailed as exc:
                if exc.response.status_code != 422 or not remaining:
                    raise GithubError(
                        f"Failed to post review on {owner}/{repo}#{number}",
                        status=exc.response.status_code,
                    ) from exc

                drop_indexes = _rejected_comment_indexes(exc, len(remaining))
                if not drop_indexes:
                    # Unknown 422 shape — drop the last comment and retry.
                    drop_indexes = {len(remaining) - 1}

                logger.warning(
                    "GitHub rejected review comments indexes=%s on %s/%s#%s; retrying without them",
                    sorted(drop_indexes),
                    owner,
                    repo,
                    number,
                )
                kept: list[ReviewComment] = []
                for idx, comment in enumerate(remaining):
                    if idx in drop_indexes:
                        rejected.append(comment)
                    else:
                        kept.append(comment)
                remaining = kept
                if not remaining and comments:
                    # All inline comments rejected — still post body-only review.
                    try:
                        await self._create_review(
                            owner=owner,
                            repo=repo,
                            number=number,
                            commit_id=commit_id,
                            body=body,
                            comments=[],
                        )
                        return PostReviewResult(posted=[], rejected=rejected)
                    except RequestFailed as body_exc:
                        raise GithubError(
                            f"Failed to post body-only review on {owner}/{repo}#{number}",
                            status=body_exc.response.status_code,
                        ) from body_exc
            except GitHubException as exc:
                raise GithubError(
                    f"Failed to post review on {owner}/{repo}#{number}"
                ) from exc

    async def _create_review(
        self,
        *,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        body: str,
        comments: list[ReviewComment],
    ) -> None:
        data: dict = {
            "commit_id": commit_id,
            "body": body,
            "event": "COMMENT",
        }
        if comments:
            data["comments"] = [
                {
                    "path": comment["path"],
                    "line": comment["line"],
                    "side": comment["side"],
                    "body": comment["body"],
                }
                for comment in comments
            ]
        await self._gh.rest.pulls.async_create_review(
            owner=owner,
            repo=repo,
            pull_number=number,
            data=data,
        )


def _rejected_comment_indexes(exc: RequestFailed, comment_count: int) -> set[int]:
    """Best-effort parse of which comment indexes GitHub rejected."""
    indexes: set[int] = set()
    try:
        payload = exc.response.json()
    except Exception:
        text = getattr(exc.response, "text", "") or str(exc)
        for match in _LINE_ERROR_RE.finditer(text):
            for group in match.groups():
                if group is not None:
                    indexes.add(int(group))
        return {i for i in indexes if 0 <= i < comment_count}

    errors = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errors, list):
        for err in errors:
            if not isinstance(err, dict):
                continue
            message = str(err.get("message", ""))
            field = str(err.get("field", ""))
            blob = f"{field} {message}"
            for match in _LINE_ERROR_RE.finditer(blob):
                for group in match.groups():
                    if group is not None:
                        indexes.add(int(group))
            if "line must be part of the diff" in message.lower() and not indexes:
                # No index — caller will fall back to dropping one at a time.
                pass

    if not indexes and isinstance(payload, dict):
        blob = json.dumps(payload)
        for match in _LINE_ERROR_RE.finditer(blob):
            for group in match.groups():
                if group is not None:
                    indexes.add(int(group))

    return {i for i in indexes if 0 <= i < comment_count}
