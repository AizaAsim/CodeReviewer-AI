"""Pydantic models for GitHub client return shapes."""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class PRMetadata(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    author: str
    base_sha: str
    head_sha: str
    changed_files: int
    additions: int
    deletions: int


class RawFile(BaseModel):
    filename: str
    status: str
    patch: str | None = None
    additions: int = 0
    deletions: int = 0
    previous_filename: str | None = None


class ReviewComment(TypedDict):
    path: str
    line: int
    side: Literal["LEFT", "RIGHT"]
    body: str


class PostReviewRequest(BaseModel):
    """Typed payload shape for post_review."""

    commit_id: str
    body: str
    comments: list[ReviewComment] = Field(default_factory=list)


class PostReviewResult(BaseModel):
    posted: list[ReviewComment] = Field(default_factory=list)
    rejected: list[ReviewComment] = Field(default_factory=list)
