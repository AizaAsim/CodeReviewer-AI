from __future__ import annotations

import uuid

from langgraph.types import Send

from codereviewer.agent.graph import route_review_passes
from codereviewer.agent.nodes.decide import decide
from codereviewer.agent.nodes.severity_gate import severity_gate
from codereviewer.agent.state import FileClass, Finding, TokenBudget
from codereviewer.diff_engine.models import DiffFile


def _base_state() -> dict:
    return {
        "run_id": uuid.uuid4(),
        "repo": "AizaAsim/codereviewer-testbed",
        "pr_number": 1,
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


def test_severity_gate_drops_low_confidence_and_dedupes() -> None:
    state = _base_state()
    state["findings"] = [
        Finding(
            path="app/x.py",
            line=10,
            side="RIGHT",
            severity="warning",
            category="logic",
            message="lower severity",
            confidence=0.9,
        ),
        Finding(
            path="app/x.py",
            line=10,
            side="RIGHT",
            severity="critical",
            category="logic",
            message="higher severity",
            confidence=0.95,
        ),
        Finding(
            path="app/x.py",
            line=12,
            side="RIGHT",
            severity="warning",
            category="logic",
            message="too low confidence",
            confidence=0.8,
        ),
    ]

    result = severity_gate(state)
    assert len(result["filtered"]) == 1
    assert result["filtered"][0].severity == "critical"
    assert result["filtered"][0].message == "higher severity"


def test_severity_gate_drops_docstring_noise() -> None:
    state = _base_state()
    state["findings"] = [
        Finding(
            path="app/mathutil.py",
            line=5,
            side="RIGHT",
            severity="warning",
            category="logic",
            message="Consider adding a docstring to explain the purpose",
            confidence=0.95,
        )
    ]
    assert severity_gate(state)["filtered"] == []


def test_severity_gate_drops_nits_when_findings_are_plentiful() -> None:
    state = _base_state()
    state["findings"] = [
        Finding(
            path="a.py",
            line=1,
            side="RIGHT",
            severity="nit",
            category="logic",
            message="nit",
            confidence=0.9,
        ),
        Finding(
            path="a.py",
            line=2,
            side="RIGHT",
            severity="warning",
            category="logic",
            message="warn1",
            confidence=0.9,
        ),
        Finding(
            path="a.py",
            line=3,
            side="RIGHT",
            severity="warning",
            category="logic",
            message="warn2",
            confidence=0.9,
        ),
    ]

    result = severity_gate(state)
    assert [item.severity for item in result["filtered"]] == ["warning", "warning"]


def test_decide_skip_approve_and_comment() -> None:
    state = _base_state()
    assert decide(state)["decision"] == "skip"

    state["files"] = [DiffFile(path="x.py", language="python", status="modified", hunks=[])]
    assert decide(state)["decision"] == "approve_note"

    state["filtered"] = [
        Finding(
            path="x.py",
            line=1,
            side="RIGHT",
            severity="warning",
            category="logic",
            message="issue",
            confidence=0.9,
        )
    ]
    assert decide(state)["decision"] == "comment"


def test_route_review_passes_skips_when_no_files() -> None:
    assert route_review_passes(_base_state()) == "skip_node"


def test_route_review_passes_fans_out_expected_passes() -> None:
    state = _base_state()
    state["files"] = [
        DiffFile(path="app/a.py", language="python", status="modified", hunks=[]),
        DiffFile(path="README.md", language="markdown", status="modified", hunks=[]),
    ]
    state["classifications"] = {
        "app/a.py": FileClass(kind="logic", risk="high", language="python"),
        "README.md": FileClass(kind="docs", risk="low", language="markdown"),
    }
    routed = route_review_passes(state)
    assert isinstance(routed, list)
    assert all(isinstance(item, Send) for item in routed)
    assert [item.node for item in routed] == [
        "security_pass",
        "logic_pass",
        "style_pass",
        "style_pass",
    ]
