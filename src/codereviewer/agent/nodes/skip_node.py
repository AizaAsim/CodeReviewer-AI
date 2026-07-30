from __future__ import annotations

from typing import Any

from codereviewer.agent.state import ReviewState


def skip_node(state: ReviewState) -> dict[str, Any]:
    return {"decision": "skip"}
