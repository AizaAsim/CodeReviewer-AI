"""Pure diff parsing, noise filtering, and token budgeting (no I/O, no LLM)."""

from __future__ import annotations

from pathlib import PurePosixPath

from unidiff import LINE_TYPE_ADDED, LINE_TYPE_CONTEXT, LINE_TYPE_REMOVED, PatchSet
from unidiff.errors import UnidiffParseError

from codereviewer.diff_engine.models import DiffFile, DiffLine, Hunk
from codereviewer.github_client.models import RawFile

_LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "uv.lock",
        "poetry.lock",
        "go.sum",
        "yarn.lock",
        "Cargo.lock",
        "composer.lock",
    }
)

_NOISE_DIR_PARTS = frozenset({"dist", "build", "vendor", "node_modules"})

_EXTENSION_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".r": "r",
    ".lua": "lua",
    ".ex": "elixir",
    ".exs": "elixir",
    ".hs": "haskell",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}

_CODE_LANGUAGES = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "go",
        "rust",
        "java",
        "kotlin",
        "ruby",
        "php",
        "c",
        "cpp",
        "csharp",
        "swift",
        "scala",
        "shell",
        "sql",
        "r",
        "lua",
        "elixir",
        "haskell",
    }
)

_LINE_TYPE_MAP = {
    LINE_TYPE_ADDED: "added",
    LINE_TYPE_REMOVED: "removed",
    LINE_TYPE_CONTEXT: "context",
}


def language_from_path(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return _EXTENSION_LANGUAGE.get(suffix, "unknown")


def _wrap_patch(path: str, patch: str, previous_filename: str | None) -> str:
    """GitHub's `patch` field omits file headers; unidiff needs them."""
    old_path = previous_filename or path
    text = patch if patch.endswith("\n") else patch + "\n"
    return f"--- a/{old_path}\n+++ b/{path}\n{text}"


def parse_files(raw: list[RawFile]) -> list[DiffFile]:
    """Parse RawFile patches into DiffFiles with exact target/source line numbers."""
    parsed: list[DiffFile] = []
    for item in raw:
        if item.patch is None:
            continue
        wrapped = _wrap_patch(item.filename, item.patch, item.previous_filename)
        try:
            patch_set = PatchSet(wrapped)
        except UnidiffParseError:
            continue

        hunks: list[Hunk] = []
        for patched_file in patch_set:
            for hunk in patched_file:
                lines: list[DiffLine] = []
                for line in hunk:
                    mapped = _LINE_TYPE_MAP.get(line.line_type)
                    if mapped is None:
                        continue
                    content = line.value.rstrip("\n")
                    lines.append(
                        DiffLine(
                            content=content,
                            type=mapped,  # type: ignore[arg-type]
                            target_line=line.target_line_no,
                            source_line=line.source_line_no,
                        )
                    )
                hunks.append(
                    Hunk(header=str(hunk).splitlines()[0], lines=lines)
                )

        parsed.append(
            DiffFile(
                path=item.filename,
                language=language_from_path(item.filename),
                status=item.status,
                hunks=hunks,
            )
        )
    return parsed


def _path_parts(path: str) -> set[str]:
    return set(PurePosixPath(path).parts)


def _is_minified(path: str) -> bool:
    name = PurePosixPath(path).name
    return ".min." in name.lower()


def _changed_line_count(file: DiffFile) -> int:
    return sum(
        1
        for hunk in file.hunks
        for line in hunk.lines
        if line.type in ("added", "removed")
    )


def _is_pure_deletion(file: DiffFile) -> bool:
    types = {line.type for hunk in file.hunks for line in hunk.lines}
    return "removed" in types and "added" not in types


def filter_noise(files: list[DiffFile]) -> tuple[list[DiffFile], list[str]]:
    """Drop lockfiles, build artifacts, huge diffs, and pure deletions.

    Returns (kept_files, dropped_paths).
    """
    kept: list[DiffFile] = []
    dropped: list[str] = []

    for file in files:
        name = PurePosixPath(file.path).name
        parts = _path_parts(file.path)

        if name in _LOCKFILE_NAMES:
            dropped.append(file.path)
            continue
        if parts & _NOISE_DIR_PARTS:
            dropped.append(file.path)
            continue
        if _is_minified(file.path):
            dropped.append(file.path)
            continue
        if _changed_line_count(file) > 800:
            dropped.append(file.path)
            continue
        if _is_pure_deletion(file):
            dropped.append(file.path)
            continue

        kept.append(file)

    return kept, dropped


def estimate_tokens(file: DiffFile) -> int:
    text = "\n".join(
        line.content for hunk in file.hunks for line in hunk.lines
    )
    return max(1, len(text) // 4) if text else 0


def budget_hunks(
    files: list[DiffFile], max_tokens: int
) -> tuple[list[DiffFile], list[str]]:
    """Fit files under a token budget.

    Priority: code languages first, then smallest (by estimated tokens) first.
    Returns (included_files, excluded_paths).
    """
    ranked = sorted(
        files,
        key=lambda f: (
            0 if f.language in _CODE_LANGUAGES else 1,
            estimate_tokens(f),
            f.path,
        ),
    )

    included: list[DiffFile] = []
    excluded: list[str] = []
    used = 0

    for file in ranked:
        cost = estimate_tokens(file)
        if used + cost <= max_tokens:
            included.append(file)
            used += cost
        else:
            excluded.append(file.path)

    # Preserve a stable-ish order: original relative order among included
    included_paths = {f.path for f in included}
    ordered = [f for f in files if f.path in included_paths]
    return ordered, excluded
