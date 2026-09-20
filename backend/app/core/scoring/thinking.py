"""Separate a thinking model's reasoning trace from its final answer."""

from __future__ import annotations

import re

_CLOSED = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
_OPEN_ONLY = re.compile(r"<think(?:ing)?>(.*)$", re.DOTALL | re.IGNORECASE)


def split_thinking(content: str, thinking_field: str | None = None) -> tuple[str, str | None]:
    """Return (answer, reasoning_trace).

    Handles the structured `thinking` field and inline <think>...</think> blocks (also an
    unterminated <think>, e.g. when generation was cut off mid-thought: the answer is then empty).
    """
    traces: list[str] = []
    if thinking_field and thinking_field.strip():
        traces.append(thinking_field.strip())

    def _grab(m: re.Match) -> str:
        if m.group(1).strip():
            traces.append(m.group(1).strip())
        return ""

    answer = _CLOSED.sub(_grab, content)
    answer = _OPEN_ONLY.sub(_grab, answer)
    trace = "\n\n".join(traces) if traces else None
    return answer.strip(), trace
