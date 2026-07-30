"""Unit tests for diff_engine — exact target_line coverage is load-bearing."""

from __future__ import annotations

from codereviewer.diff_engine.parser import (
    budget_hunks,
    estimate_tokens,
    filter_noise,
    language_from_path,
    parse_files,
)
from codereviewer.github_client.models import RawFile
from tests.fixtures.patches import (
    LOCKFILE_PATCH,
    MINIFIED_PATCH,
    MULTI_HUNK_PATCH,
    PURE_DELETE_PATCH,
    RENAMED_PATCH,
)


def test_language_from_path() -> None:
    assert language_from_path("app/users.py") == "python"
    assert language_from_path("src/App.tsx") == "typescript"
    assert language_from_path("README.md") == "markdown"
    assert language_from_path("weird") == "unknown"


def test_parse_multi_hunk_exact_target_lines() -> None:
    raw = [
        RawFile(filename="foo.py", status="modified", patch=MULTI_HUNK_PATCH),
    ]
    files = parse_files(raw)
    assert len(files) == 1
    f = files[0]
    assert f.path == "foo.py"
    assert f.language == "python"
    assert f.status == "modified"
    assert len(f.hunks) == 2

    h1 = f.hunks[0]
    assert h1.header.startswith("@@ -1,3 +1,4 @@")
    # Exact target/source lines — GitHub inline comments depend on these.
    assert [(ln.type, ln.source_line, ln.target_line, ln.content) for ln in h1.lines] == [
        ("context", 1, 1, "line1"),
        ("removed", 2, None, "line2"),
        ("added", None, 2, "line2 changed"),
        ("context", 3, 3, "line3"),
        ("added", None, 4, "line4"),
    ]

    h2 = f.hunks[1]
    assert [(ln.type, ln.source_line, ln.target_line, ln.content) for ln in h2.lines] == [
        ("context", 20, 21, "ctx"),
        ("added", None, 22, "added"),
        ("context", 21, 23, "ctx2"),
    ]


def test_parse_renamed_file() -> None:
    raw = [
        RawFile(
            filename="new.py",
            status="renamed",
            patch=RENAMED_PATCH,
            previous_filename="old.py",
        )
    ]
    files = parse_files(raw)
    assert len(files) == 1
    assert files[0].path == "new.py"
    assert files[0].status == "renamed"
    lines = files[0].hunks[0].lines
    assert lines[0].type == "removed" and lines[0].source_line == 1 and lines[0].target_line is None
    assert lines[1].type == "added" and lines[1].target_line == 1 and lines[1].source_line is None


def test_parse_missing_patch_skipped() -> None:
    raw = [
        RawFile(filename="binary.png", status="added", patch=None),
        RawFile(filename="ok.py", status="modified", patch=MULTI_HUNK_PATCH),
    ]
    files = parse_files(raw)
    assert [f.path for f in files] == ["ok.py"]


def test_filter_noise_lockfile() -> None:
    files = parse_files(
        [RawFile(filename="package-lock.json", status="modified", patch=LOCKFILE_PATCH)]
    )
    kept, dropped = filter_noise(files)
    assert kept == []
    assert dropped == ["package-lock.json"]


def test_filter_noise_vendor_and_minified() -> None:
    files = parse_files(
        [
            RawFile(filename="vendor/lib/x.py", status="modified", patch=MINIFIED_PATCH),
            RawFile(filename="assets/app.min.js", status="modified", patch=MINIFIED_PATCH),
            RawFile(filename="app/ok.py", status="modified", patch=MINIFIED_PATCH),
        ]
    )
    kept, dropped = filter_noise(files)
    assert [f.path for f in kept] == ["app/ok.py"]
    assert set(dropped) == {"vendor/lib/x.py", "assets/app.min.js"}


def test_filter_noise_pure_deletion() -> None:
    files = parse_files(
        [RawFile(filename="gone.py", status="removed", patch=PURE_DELETE_PATCH)]
    )
    kept, dropped = filter_noise(files)
    assert kept == []
    assert dropped == ["gone.py"]


def test_filter_noise_huge_file() -> None:
    # Build a patch with >800 changed lines
    body_lines = [f"+line{i}" for i in range(801)]
    patch = "@@ -0,0 +1,801 @@\n" + "\n".join(body_lines) + "\n"
    files = parse_files([RawFile(filename="big.py", status="added", patch=patch)])
    kept, dropped = filter_noise(files)
    assert kept == []
    assert dropped == ["big.py"]


def test_budget_hunks_prefers_code_then_smallest() -> None:
    small_py = parse_files(
        [RawFile(filename="a.py", status="modified", patch=MINIFIED_PATCH)]
    )[0]
    large_md_patch = (
        "@@ -0,0 +1,20 @@\n"
        + "\n".join([f"+doc line {i} " + ("x" * 40) for i in range(20)])
        + "\n"
    )
    large_md = parse_files(
        [RawFile(filename="NOTES.md", status="modified", patch=large_md_patch)]
    )[0]
    medium_py_patch = (
        "@@ -0,0 +1,5 @@\n"
        + "\n".join([f"+code{i}" for i in range(5)])
        + "\n"
    )
    medium_py = parse_files(
        [RawFile(filename="b.py", status="modified", patch=medium_py_patch)]
    )[0]

    # Budget only enough for both python files if code is preferred over md
    files = [large_md, medium_py, small_py]
    tokens_small = estimate_tokens(small_py)
    tokens_medium = estimate_tokens(medium_py)
    budget = tokens_small + tokens_medium
    included, excluded = budget_hunks(files, max_tokens=budget)

    assert {f.path for f in included} == {"a.py", "b.py"}
    assert excluded == ["NOTES.md"]


def test_budget_excludes_when_over() -> None:
    files = parse_files(
        [
            RawFile(filename="a.py", status="modified", patch=MULTI_HUNK_PATCH),
            RawFile(filename="b.py", status="modified", patch=MULTI_HUNK_PATCH),
        ]
    )
    included, excluded = budget_hunks(files, max_tokens=1)
    # At most one tiny file might fit if estimate is 0; with real content none or one
    assert len(included) + len(excluded) == 2
    assert len(excluded) >= 1
