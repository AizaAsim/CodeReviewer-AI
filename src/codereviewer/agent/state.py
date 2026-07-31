"""Review agent state models for the LangGraph review pipeline."""

from __future__ import annotations

import operator
import uuid
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field

from codereviewer.diff_engine.models import DiffFile
from codereviewer.github_client.models import PRMetadata, RawFile

ReviewDecision = Literal["comment", "approve_note", "skip"]


class FileClass(BaseModel):
    kind: Literal["logic", "config", "test", "docs"]
    risk: Literal["high", "medium", "low"]
    language: str


class ClassifiedFile(BaseModel):
    path: str
    kind: Literal["logic", "config", "test", "docs"]
    risk: Literal["high", "medium", "low"]
    language: str


class Finding(BaseModel):
    path: str
    line: int
    side: Literal["LEFT", "RIGHT"] = "RIGHT"
    severity: Literal["critical", "warning", "nit"]
    category: Literal["security", "logic", "style"]
    message: str
    confidence: float
    suggestion: str | None = None


class FindingList(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


class ClassificationList(BaseModel):
    files: list[ClassifiedFile] = Field(default_factory=list)


class PostedComment(BaseModel):
    path: str
    line: int
    side: Literal["LEFT", "RIGHT"]
    body: str


class TokenBudget(BaseModel):
    total: int = 6000
    spent: int = 0
    remaining: int = 6000


class ReviewState(TypedDict):
    run_id: uuid.UUID
    repo: str
    pr_number: int
    installation_id: int | None
    pr: PRMetadata | None
    raw_files: list[RawFile]
    files: list[DiffFile]
    current_file: DiffFile | None
    classifications: dict[str, FileClass]
    findings: Annotated[list[Finding], operator.add]
    filtered: list[Finding]
    decision: ReviewDecision
    posted: list[PostedComment]
    budget: TokenBudget
    token_events: Annotated[list[int], operator.add]
