from __future__ import annotations

from typing import Any

from codereviewer.agent.state import ReviewState
from codereviewer.diff_engine import budget_hunks, estimate_tokens, filter_noise, parse_files


def filter_noise_node(state: ReviewState) -> dict[str, Any]:
    parsed = parse_files(state["raw_files"])
    kept, _dropped = filter_noise(parsed)
    budgeted, _excluded = budget_hunks(kept, max_tokens=state["budget"].total)
    budgeted_tokens = sum(estimate_tokens(file) for file in budgeted)
    budget = state["budget"].model_copy(
        update={"remaining": max(0, state["budget"].total - budgeted_tokens)}
    )
    return {"files": budgeted, "budget": budget}
