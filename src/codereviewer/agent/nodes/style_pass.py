from __future__ import annotations

from codereviewer.agent.nodes.common import invoke_structured, render_file
from codereviewer.agent.prompts import (
    STYLE_REVIEW_SYSTEM_PROMPT,
    STYLE_REVIEW_USER_TEMPLATE,
)
from codereviewer.agent.state import FindingList, ReviewState


async def style_pass(state: ReviewState) -> ReviewState:
    file = state["current_file"]
    if file is None:
        return {"findings": [], "token_events": []}  # type: ignore[return-value]

    prompt = STYLE_REVIEW_USER_TEMPLATE.format(
        path=file.path,
        language=file.language,
        status=file.status,
        annotated_diff=render_file(file),
    )
    parsed, tokens = await invoke_structured(
        FindingList,
        system_prompt=STYLE_REVIEW_SYSTEM_PROMPT,
        user_prompt=prompt,
    )
    for finding in parsed.findings:
        finding.category = "style"
        if finding.severity != "nit":
            finding.severity = "nit"
    return {"findings": parsed.findings, "token_events": [tokens]}  # type: ignore[return-value]
