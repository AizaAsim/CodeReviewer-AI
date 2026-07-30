"""GitHub client error types."""

from __future__ import annotations


class GithubError(Exception):
    """Wraps an upstream GitHub API failure."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
