from __future__ import annotations

from typing import Any

from codereviewer.agent.state import Finding, ReviewState

# Raised from 0.7 → 0.85 after eval showed clean-PR docstring noise at 0.7.
CONFIDENCE_THRESHOLD = 0.85

_SEVERITY_ORDER = {"nit": 0, "warning": 1, "critical": 2}
_CATEGORY_ORDER = {"style": 0, "logic": 1, "security": 2}

_NOISE_PHRASES = (
    "docstring",
    "consider adding",
    "add a comment",
    "missing comment",
    "type hint",
    "more readable",
)


def _rank(finding: Finding) -> tuple[int, int]:
    return (_SEVERITY_ORDER[finding.severity], _CATEGORY_ORDER[finding.category])


def _is_low_value_noise(finding: Finding) -> bool:
    message = finding.message.lower()
    return any(phrase in message for phrase in _NOISE_PHRASES)


def severity_gate(state: ReviewState) -> dict[str, Any]:
    by_line: dict[tuple[str, int], Finding] = {}

    for finding in state["findings"]:
        if finding.confidence < CONFIDENCE_THRESHOLD:
            continue
        if _is_low_value_noise(finding):
            continue
        key = (finding.path, finding.line)
        current = by_line.get(key)
        if current is None or _rank(finding) > _rank(current):
            by_line[key] = finding

    filtered = sorted(by_line.values(), key=lambda item: (item.path, item.line))
    # Keep nits only when the total surviving set is still small.
    if len(filtered) >= 3:
        filtered = [item for item in filtered if item.severity != "nit"]

    return {"filtered": filtered[:10]}
