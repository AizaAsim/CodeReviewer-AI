"""Background review runner — executes the LangGraph agent and persists results."""

from __future__ import annotations

import logging
import time
import uuid

from groq import APIStatusError, RateLimitError

from codereviewer.agent.graph import review_graph
from codereviewer.agent.state import TokenBudget
from codereviewer.persistence.models import AsyncSessionLocal, ReviewRun
from codereviewer.persistence.models import Finding as FindingRecord

logger = logging.getLogger(__name__)


async def run_review(
    run_id: uuid.UUID, installation_id: int | None = None
) -> None:
    """Run the review graph, persist findings, and record posted status."""
    logger.info("run_review started run_id=%s", run_id)
    started = time.perf_counter()

    async with AsyncSessionLocal() as session:
        run = await session.get(ReviewRun, run_id)
        if run is None:
            logger.warning("run_review: ReviewRun not found run_id=%s", run_id)
            return
        run.status = "reviewing"
        await session.commit()

    try:
        async with AsyncSessionLocal() as session:
            run = await session.get(ReviewRun, run_id)
            if run is None:
                logger.warning("run_review: ReviewRun disappeared run_id=%s", run_id)
                return

            state = await review_graph.ainvoke(
                {
                    "run_id": run_id,
                    "repo": run.repo,
                    "pr_number": run.pr_number,
                    "installation_id": installation_id,
                    "pr": None,
                    "raw_files": [],
                    "files": [],
                    "current_file": None,
                    "classifications": {},
                    "findings": [],
                    "filtered": [],
                    "decision": "skip",
                    "posted": [],
                    "budget": TokenBudget(),
                    "token_events": [],
                }
            )

            posted_keys = {(item.path, item.line) for item in state["posted"]}

            await session.refresh(run)
            await session.execute(
                FindingRecord.__table__.delete().where(FindingRecord.run_id == run_id)
            )
            for finding in state["findings"]:
                session.add(
                    FindingRecord(
                        run_id=run_id,
                        path=finding.path,
                        line=finding.line,
                        side=finding.side,
                        severity=finding.severity,
                        category=finding.category,
                        confidence=finding.confidence,
                        message=finding.message,
                        suggestion=finding.suggestion,
                        posted=(finding.path, finding.line) in posted_keys,
                    )
                )

            run.decision = state["decision"]
            run.files_reviewed = len(state["files"])
            run.findings_raw = len(state["findings"])
            run.findings_posted = len(state["posted"])
            run.tokens_used = state["budget"].spent
            run.duration_ms = int((time.perf_counter() - started) * 1000)
            if state["decision"] == "skip":
                run.status = "skipped"
            else:
                run.status = "posted"

            await session.commit()
    except (RateLimitError, APIStatusError) as exc:
        async with AsyncSessionLocal() as session:
            run = await session.get(ReviewRun, run_id)
            if run is not None:
                run.status = "failed"
                run.duration_ms = int((time.perf_counter() - started) * 1000)
                await session.commit()
        logger.exception("run_review failed for run_id=%s", run_id)
        raise exc
    except Exception:
        async with AsyncSessionLocal() as session:
            run = await session.get(ReviewRun, run_id)
            if run is not None:
                run.status = "failed"
                run.duration_ms = int((time.perf_counter() - started) * 1000)
                await session.commit()
        logger.exception("run_review failed for run_id=%s", run_id)
        raise
