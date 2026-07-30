"""Repository helpers for review runs."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from codereviewer.persistence.models import ReviewRun


async def create_review_run_if_absent(
    session: AsyncSession,
    *,
    repo: str,
    pr_number: int,
    head_sha: str,
) -> uuid.UUID | None:
    """Insert a ReviewRun with status=received.

    Returns the new run id, or None if (repo, pr_number, head_sha) already exists.
    """
    stmt = (
        insert(ReviewRun)
        .values(
            id=uuid.uuid4(),
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
            status="received",
        )
        .on_conflict_do_nothing(constraint="uq_review_run_commit")
        .returning(ReviewRun.id)
    )
    result = await session.execute(stmt)
    run_id = result.scalar_one_or_none()
    if run_id is not None:
        await session.commit()
        return run_id

    await session.rollback()
    existing = await session.execute(
        select(ReviewRun.id).where(
            ReviewRun.repo == repo,
            ReviewRun.pr_number == pr_number,
            ReviewRun.head_sha == head_sha,
        )
    )
    _ = existing.scalar_one_or_none()
    return None
