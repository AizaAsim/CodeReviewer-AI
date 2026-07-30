#!/usr/bin/env python3
"""Standalone evaluation harness for CodeReviewer AI.

Requires a running API with EVAL_TOKEN configured:

  export EVAL_BASE_URL=http://127.0.0.1:8000
  export EVAL_TOKEN=...
  uv run python eval/run_eval.py
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

console = Console()

DEFAULT_DATASET = Path(__file__).with_name("dataset.jsonl")
DEFAULT_RESULTS = Path(__file__).with_name("results.json")
DEFAULT_RUNS = 3


@dataclass
class PlantedIssue:
    path: str
    line_range: tuple[int, int]
    category: str
    note: str = ""


@dataclass
class DatasetRow:
    repo: str
    pr_number: int
    planted_issues: list[PlantedIssue]


@dataclass
class RunScore:
    repo: str
    pr_number: int
    decision: str
    tokens_used: int
    duration_ms: int
    files_reviewed: int
    findings_posted: int
    true_positives: int
    false_positives: int
    false_negatives: int
    recall: float
    precision: float
    noise: int
    is_clean: bool
    by_category: dict[str, dict[str, float]]


def load_dataset(path: Path) -> list[DatasetRow]:
    rows: list[DatasetRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        raw = json.loads(line)
        issues = [
            PlantedIssue(
                path=item["path"],
                line_range=(int(item["line_range"][0]), int(item["line_range"][1])),
                category=item["category"],
                note=item.get("note", ""),
            )
            for item in raw.get("planted_issues", [])
        ]
        rows.append(
            DatasetRow(
                repo=raw["repo"],
                pr_number=int(raw["pr_number"]),
                planted_issues=issues,
            )
        )
    return rows


def _in_range(line: int, line_range: tuple[int, int]) -> bool:
    lo, hi = line_range
    return lo <= line <= hi


def score_run(row: DatasetRow, payload: dict[str, Any]) -> RunScore:
    # Score against gated findings (what would be posted).
    findings = payload.get("filtered") or []
    is_clean = len(row.planted_issues) == 0

    matched_issue_indexes: set[int] = set()
    matched_finding_indexes: set[int] = set()

    for i, issue in enumerate(row.planted_issues):
        for j, finding in enumerate(findings):
            if j in matched_finding_indexes:
                continue
            if finding.get("path") != issue.path:
                continue
            if finding.get("category") != issue.category:
                continue
            if not _in_range(int(finding.get("line", -1)), issue.line_range):
                continue
            matched_issue_indexes.add(i)
            matched_finding_indexes.add(j)
            break

    true_positives = len(matched_issue_indexes)
    false_negatives = len(row.planted_issues) - true_positives
    false_positives = len(findings) - len(matched_finding_indexes)
    noise = len(findings) if is_clean else 0

    recall = (
        true_positives / len(row.planted_issues) if row.planted_issues else 1.0
    )
    precision = (
        (true_positives / len(findings)) if findings else (1.0 if is_clean else 0.0)
    )

    by_category: dict[str, dict[str, float]] = {}
    categories = sorted(
        {
            *(issue.category for issue in row.planted_issues),
            *(str(f.get("category")) for f in findings),
        }
    )
    for category in categories:
        cat_issues = [
            (i, issue)
            for i, issue in enumerate(row.planted_issues)
            if issue.category == category
        ]
        cat_findings = [
            (j, finding)
            for j, finding in enumerate(findings)
            if finding.get("category") == category
        ]
        cat_matched_issues: set[int] = set()
        cat_matched_findings: set[int] = set()
        for i, issue in cat_issues:
            for j, finding in cat_findings:
                if j in cat_matched_findings:
                    continue
                if finding.get("path") != issue.path:
                    continue
                if not _in_range(int(finding.get("line", -1)), issue.line_range):
                    continue
                cat_matched_issues.add(i)
                cat_matched_findings.add(j)
                break
        tp = len(cat_matched_issues)
        fn = len(cat_issues) - tp
        fp = len(cat_findings) - len(cat_matched_findings)
        by_category[category] = {
            "tp": float(tp),
            "fp": float(fp),
            "fn": float(fn),
            "recall": (tp / len(cat_issues)) if cat_issues else 1.0,
            "precision": (tp / len(cat_findings)) if cat_findings else (1.0 if not cat_issues else 0.0),
        }

    return RunScore(
        repo=row.repo,
        pr_number=row.pr_number,
        decision=str(payload.get("decision", "")),
        tokens_used=int(payload.get("tokens_used", 0)),
        duration_ms=int(payload.get("duration_ms", 0)),
        files_reviewed=int(payload.get("files_reviewed", 0)),
        findings_posted=len(findings),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        recall=recall,
        precision=precision,
        noise=noise,
        is_clean=is_clean,
        by_category=by_category,
    )


def call_eval(
    client: httpx.Client,
    *,
    base_url: str,
    token: str,
    repo: str,
    pr_number: int,
) -> dict[str, Any]:
    response = client.post(
        f"{base_url.rstrip('/')}/eval/review",
        headers={"Authorization": f"Bearer {token}"},
        json={"repo": repo, "pr_number": pr_number},
        timeout=180.0,
    )
    response.raise_for_status()
    return response.json()


def mean_spread(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    mean = statistics.fmean(values)
    # Sample stdev as "spread"
    spread = statistics.stdev(values)
    return mean, spread


def print_tables(all_runs: list[list[RunScore]]) -> None:
    # Flatten per outer trial then aggregate.
    overall_recalls: list[float] = []
    overall_precisions: list[float] = []
    overall_noise: list[float] = []
    overall_tokens: list[float] = []
    overall_latency: list[float] = []

    category_stats: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"recall": [], "precision": []}
    )

    for trial in all_runs:
        tp = sum(r.true_positives for r in trial)
        fp = sum(r.false_positives for r in trial)
        fn = sum(r.false_negatives for r in trial)
        noise = sum(r.noise for r in trial)
        tokens = sum(r.tokens_used for r in trial)
        latency = statistics.fmean([r.duration_ms for r in trial]) if trial else 0.0

        recall = tp / (tp + fn) if (tp + fn) else 1.0
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        overall_recalls.append(recall)
        overall_precisions.append(precision)
        overall_noise.append(float(noise))
        overall_tokens.append(float(tokens))
        overall_latency.append(float(latency))

        # Per-category micro averages for this trial
        cat_tp: dict[str, float] = defaultdict(float)
        cat_fp: dict[str, float] = defaultdict(float)
        cat_fn: dict[str, float] = defaultdict(float)
        for run in trial:
            for category, stats in run.by_category.items():
                cat_tp[category] += stats["tp"]
                cat_fp[category] += stats["fp"]
                cat_fn[category] += stats["fn"]
        for category in sorted(set(cat_tp) | set(cat_fp) | set(cat_fn)):
            tp_c = cat_tp[category]
            fp_c = cat_fp[category]
            fn_c = cat_fn[category]
            category_stats[category]["recall"].append(
                tp_c / (tp_c + fn_c) if (tp_c + fn_c) else 1.0
            )
            category_stats[category]["precision"].append(
                tp_c / (tp_c + fp_c) if (tp_c + fp_c) else 1.0
            )

    cat_table = Table(title="Eval by category (mean ± spread across trials)")
    cat_table.add_column("category")
    cat_table.add_column("recall")
    cat_table.add_column("precision")
    for category, values in sorted(category_stats.items()):
        r_mean, r_spread = mean_spread(values["recall"])
        p_mean, p_spread = mean_spread(values["precision"])
        cat_table.add_row(
            category,
            f"{r_mean:.2f}±{r_spread:.2f}",
            f"{p_mean:.2f}±{p_spread:.2f}",
        )
    console.print(cat_table)

    overall = Table(title="Overall (mean ± spread across trials)")
    overall.add_column("metric")
    overall.add_column("value")
    for label, values in [
        ("recall", overall_recalls),
        ("precision", overall_precisions),
        ("noise (findings on clean PRs)", overall_noise),
        ("tokens / trial", overall_tokens),
        ("avg latency ms / PR", overall_latency),
    ]:
        mean, spread = mean_spread(values)
        overall.add_row(label, f"{mean:.2f}±{spread:.2f}")
    console.print(overall)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CodeReviewer AI evaluation harness")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVAL_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--token", default=os.environ.get("EVAL_TOKEN", ""))
    args = parser.parse_args(argv)

    if not args.token:
        console.print("[red]EVAL_TOKEN is required (env or --token)[/red]")
        return 2

    dataset = load_dataset(args.dataset)
    if not dataset:
        console.print(f"[red]No dataset rows in {args.dataset}[/red]")
        return 2

    all_runs: list[list[RunScore]] = []
    with httpx.Client() as client:
        for trial_idx in range(1, args.runs + 1):
            console.print(f"[bold]Trial {trial_idx}/{args.runs}[/bold]")
            trial_scores: list[RunScore] = []
            for row in dataset:
                console.print(f"  reviewing {row.repo}#{row.pr_number} ...", end="")
                try:
                    payload = call_eval(
                        client,
                        base_url=args.base_url,
                        token=args.token,
                        repo=row.repo,
                        pr_number=row.pr_number,
                    )
                except Exception as exc:
                    console.print(f" [red]failed[/red] ({exc})")
                    return 1
                score = score_run(row, payload)
                trial_scores.append(score)
                console.print(
                    f" decision={score.decision} posted={score.findings_posted} "
                    f"R={score.recall:.2f} P={score.precision:.2f} "
                    f"tokens={score.tokens_used} {score.duration_ms}ms"
                )
            all_runs.append(trial_scores)

    print_tables(all_runs)

    payload = {
        "runs": args.runs,
        "dataset": str(args.dataset),
        "trials": [[asdict(score) for score in trial] for trial in all_runs],
    }
    args.results.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    console.print(f"[green]Wrote {args.results}[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
