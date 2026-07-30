from __future__ import annotations

import asyncio

from groq import APIStatusError, RateLimitError
from langchain_groq import ChatGroq
from pydantic import BaseModel

from codereviewer.config import settings
from codereviewer.diff_engine.models import DiffFile, DiffLine


def render_line(line: DiffLine) -> str:
    marker = {"added": "+", "removed": "-", "context": " "}[line.type]
    number = line.target_line if line.target_line is not None else line.source_line
    number_text = "?" if number is None else str(number)
    return f"{number_text} {marker} {line.content}"


def render_file(file: DiffFile) -> str:
    chunks: list[str] = []
    for hunk in file.hunks:
        chunks.append(hunk.header)
        chunks.extend(render_line(line) for line in hunk.lines)
    return "\n".join(chunks)


async def invoke_structured(
    schema: type[BaseModel],
    *,
    system_prompt: str,
    user_prompt: str,
) -> tuple[BaseModel, int]:
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.1,
        api_key=settings.groq_api_key,
    )
    runner = llm.with_structured_output(schema, include_raw=True)

    for attempt in range(3):
        try:
            result = await runner.ainvoke(
                [("system", system_prompt), ("user", user_prompt)]
            )
            parsed = result["parsed"]
            raw = result["raw"]
            usage = getattr(raw, "usage_metadata", {}) or {}
            return parsed, int(usage.get("total_tokens", 0))
        except RateLimitError:
            if attempt == 2:
                raise
            await asyncio.sleep(2**attempt)
        except APIStatusError as exc:
            if exc.status_code != 429 or attempt == 2:
                raise
            await asyncio.sleep(2**attempt)

    return schema(), 0
