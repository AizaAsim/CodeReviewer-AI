from __future__ import annotations

from eval.run_eval import DatasetRow, PlantedIssue, score_run


def test_score_run_perfect_match() -> None:
    row = DatasetRow(
        repo="AizaAsim/codereviewer-testbed",
        pr_number=1,
        planted_issues=[
            PlantedIssue(
                path="app/users.py",
                line_range=(6, 6),
                category="security",
            )
        ],
    )
    payload = {
        "decision": "comment",
        "tokens_used": 100,
        "duration_ms": 50,
        "files_reviewed": 1,
        "filtered": [
            {
                "path": "app/users.py",
                "line": 6,
                "category": "security",
                "severity": "critical",
            }
        ],
    }
    score = score_run(row, payload)
    assert score.recall == 1.0
    assert score.precision == 1.0
    assert score.noise == 0


def test_score_run_clean_noise() -> None:
    row = DatasetRow(repo="x/y", pr_number=6, planted_issues=[])
    payload = {
        "decision": "comment",
        "tokens_used": 10,
        "duration_ms": 10,
        "files_reviewed": 1,
        "filtered": [
            {
                "path": "a.py",
                "line": 1,
                "category": "logic",
                "severity": "warning",
            }
        ],
    }
    score = score_run(row, payload)
    assert score.is_clean
    assert score.noise == 1
    assert score.precision == 0.0
    assert score.recall == 1.0
