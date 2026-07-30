from __future__ import annotations

from codereviewer.agent.state import ReviewState


def aggregate_findings(state: ReviewState) -> ReviewState:
    spent = sum(state["token_events"])
    budget = state["budget"].model_copy(
        update={
            "spent": spent,
            "remaining": max(0, state["budget"].total - spent),
        }
    )
    return {"budget": budget}  # type: ignore[return-value]
