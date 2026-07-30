from __future__ import annotations

from codereviewer.agent.nodes.common import invoke_structured
from codereviewer.agent.prompts import (
    CLASSIFY_FILES_SYSTEM_PROMPT,
    CLASSIFY_FILES_USER_TEMPLATE,
)
from codereviewer.agent.state import ClassificationList, FileClass, ReviewState


async def classify_files(state: ReviewState) -> ReviewState:
    if not state["files"]:
        return {"classifications": {}, "token_events": []}  # type: ignore[return-value]

    rendered_files = "\n".join(
        f"- path={file.path} language={file.language} status={file.status}"
        for file in state["files"]
    )
    prompt = CLASSIFY_FILES_USER_TEMPLATE.format(files=rendered_files)
    parsed, tokens = await invoke_structured(
        ClassificationList,
        system_prompt=CLASSIFY_FILES_SYSTEM_PROMPT,
        user_prompt=prompt,
    )

    mapped = {
        item.path: FileClass(kind=item.kind, risk=item.risk, language=item.language)
        for item in parsed.files
    }
    for file in state["files"]:
        mapped.setdefault(
            file.path,
            FileClass(kind="logic", risk="medium", language=file.language),
        )

    return {"classifications": mapped, "token_events": [tokens]}  # type: ignore[return-value]
