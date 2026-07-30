from __future__ import annotations

from typing import Any

from codereviewer.agent.state import ReviewDecision, ReviewState


def decide(state: ReviewState) -> dict[str, Any]:
    decision: ReviewDecision
    if not state["files"]:
        decision = "skip"
    elif state["filtered"]:
        decision = "comment"
    else:
        decision = "approve_note"

    return {"decision": decision}
