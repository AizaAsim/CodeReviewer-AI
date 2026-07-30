from __future__ import annotations

from codereviewer.agent.nodes.common import invoke_structured, render_file
from codereviewer.agent.prompts import (
    SECURITY_REVIEW_SYSTEM_PROMPT,
    SECURITY_REVIEW_USER_TEMPLATE,
)
from codereviewer.agent.state import FindingList, ReviewState


async def security_pass(state: ReviewState) -> ReviewState:
    file = state["current_file"]
    if file is None:
        return {"findings": [], "token_events": []}  # type: ignore[return-value]

    prompt = SECURITY_REVIEW_USER_TEMPLATE.format(
        path=file.path,
        language=file.language,
        status=file.status,
        annotated_diff=render_file(file),
    )
    parsed, tokens = await invoke_structured(
        FindingList,
        system_prompt=SECURITY_REVIEW_SYSTEM_PROMPT,
        user_prompt=prompt,
    )
    for finding in parsed.findings:
        finding.category = "security"
    return {"findings": parsed.findings, "token_events": [tokens]}  # type: ignore[return-value]
