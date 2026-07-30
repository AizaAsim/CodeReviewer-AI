"""Diff engine data shapes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DiffLine(BaseModel):
    content: str
    type: Literal["added", "removed", "context"]
    target_line: int | None = None
    source_line: int | None = None


class Hunk(BaseModel):
    header: str
    lines: list[DiffLine] = Field(default_factory=list)


class DiffFile(BaseModel):
    path: str
    language: str
    status: str
    hunks: list[Hunk] = Field(default_factory=list)
