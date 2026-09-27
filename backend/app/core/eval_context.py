"""Built-in rubrics and the evaluation input assembler for live turns (design D6).

Reuses the existing judge machinery (`JudgeCall`, `run_judge`, `rubric_schema`) unchanged: a turn is just another
thing whose `task`/`response` get judged. The only new work here is picking a rubric and building `task` from a
turn's conversation context instead of a `RunCase.prompt`.
"""

from __future__ import annotations

from app.core.scoring.judge import JudgeCall
from app.models import Agent, AgentTurn

CHATBOT_RUBRIC = [
    {"name": "Relevance", "description": "Directly and fully addresses what the user asked"},
    {"name": "Helpfulness", "description": "Gives the user what they need to move forward"},
    {"name": "Coherence", "description": "Well written, internally consistent and easy to follow"},
    {"name": "Tone and safety", "description": "Appropriate in tone and free of unsafe or harmful content"},
]

REASONING_RUBRIC = [
    {"name": "Logical soundness", "description": "Each step follows from the previous ones and is correct"},
    {"name": "Clarity", "description": "The reasoning is easy to follow and free of contradictions"},
    {"name": "Correctness", "description": "The final answer is one a careful expert would accept"},
]

BUILTIN_RUBRICS: dict[str, list[dict]] = {"chatbot": CHATBOT_RUBRIC, "reasoning": REASONING_RUBRIC}


def resolve_rubric(agent: Agent) -> list[dict]:
    """The agent's custom rubric if set, otherwise the built-in rubric for its kind."""
    if agent.rubric:
        return agent.rubric
    return BUILTIN_RUBRICS.get(agent.kind, CHATBOT_RUBRIC)


def build_context(turn: AgentTurn, prior_turns: list[AgentTurn], *, context_turns: int, char_budget: int = 6000) -> str:
    """The last `context_turns` finished turns of the session as `User/Assistant` lines, then the current turn's
    input. Oldest lines are dropped first to stay within `char_budget` (design D6)."""
    lines: list[str] = []
    for t in prior_turns[-context_turns:]:
        if t.input:
            lines.append(f"User: {t.input}")
        if t.output:
            lines.append(f"Assistant: {t.output}")
    lines.append(f"User: {turn.input}")
    text = "\n".join(lines)
    while len(text) > char_budget and lines:
        lines.pop(0)
        text = "\n".join(lines)
    return text


def turn_response_text(turn: AgentTurn) -> str:
    """The turn's output, or its output prefixed by intermediate reasoning for multi-span turns (mirrors the
    existing `judge_reasoning` trace-plus-answer shape)."""
    traces = [s.thinking for s in turn.spans if s.kind == "llm" and s.thinking]
    if not traces:
        return turn.output or ""
    return "\n\n".join(traces) + f"\n\n{turn.output or ''}"


def build_judge_call(
    turn: AgentTurn, prior_turns: list[AgentTurn], rubric: list[dict], *, context_turns: int
) -> JudgeCall:
    task = build_context(turn, prior_turns, context_turns=context_turns)
    return JudgeCall(task=task, response=turn_response_text(turn), rubric=rubric, kind="turn_eval")
