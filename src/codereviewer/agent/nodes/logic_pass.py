from __future__ import annotations

from codereviewer.agent.prompts import (
    LOGIC_REVIEW_SYSTEM_PROMPT,
    LOGIC_REVIEW_USER_TEMPLATE,
)
from codereviewer.agent.state import FindingList, ReviewState
from codereviewer.agent.nodes.common import invoke_structured, render_file


async def logic_pass(state: ReviewState) -> ReviewState:
    file = state["current_file"]
    if file is None:
        return {"findings": [], "token_events": []}  # type: ignore[return-value]

    prompt = LOGIC_REVIEW_USER_TEMPLATE.format(
        path=file.path,
        language=file.language,
        status=file.status,
        annotated_diff=render_file(file),
    )
    parsed, tokens = await invoke_structured(
        FindingList,
        system_prompt=LOGIC_REVIEW_SYSTEM_PROMPT,
        user_prompt=prompt,
    )
    for finding in parsed.findings:
        finding.category = "logic"
    return {"findings": parsed.findings, "token_events": [tokens]}  # type: ignore[return-value]
