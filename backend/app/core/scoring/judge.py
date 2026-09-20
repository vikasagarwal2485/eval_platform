"""LLM-as-judge scoring with a rubric, using Ollama structured output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.core.scoring.base import ScoreResult
from app.ollama.client import OllamaClient, OllamaError, OllamaUnreachable

DEFAULT_GENERATION_RUBRIC = [
    {"name": "Relevance", "description": "Directly and fully addresses the request"},
    {"name": "Quality", "description": "Well written, coherent and accurate"},
]
REASONING_RUBRIC = [
    {"name": "Logical soundness", "description": "Each step follows from the previous ones and is correct"},
    {"name": "Clarity", "description": "The reasoning is easy to follow and free of contradictions"},
]

SYSTEM_PROMPT = (
    "You are a strict, impartial evaluator. Score the RESPONSE to the TASK against each criterion "
    "using an integer from 1 (very poor) to 5 (excellent). Judge only the response quality, ignore who "
    "wrote it. Reply with JSON only."
)


class JudgeParseError(ValueError):
    pass


@dataclass
class JudgeCall:
    """Everything needed to judge one response."""

    task: str
    response: str
    rubric: list[dict]
    kind: str = "judge"
    extra: dict = field(default_factory=dict)


def rubric_schema(rubric: list[dict]) -> dict:
    crit = {
        "type": "object",
        "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5}, "reason": {"type": "string"}},
        "required": ["score", "reason"],
    }
    return {
        "type": "object",
        "properties": {
            "scores": {
                "type": "object",
                "properties": {c["name"]: crit for c in rubric},
                "required": [c["name"] for c in rubric],
            }
        },
        "required": ["scores"],
    }


def build_judge_messages(call: JudgeCall) -> list[dict[str, str]]:
    criteria = "\n".join(f"- {c['name']}: {c.get('description') or ''}".rstrip(": ") for c in call.rubric)
    user = (
        f"TASK:\n{call.task}\n\nRESPONSE:\n{call.response}\n\nCRITERIA:\n{criteria}\n\n"
        'Return JSON of the form {"scores": {"<criterion>": {"score": <1-5>, "reason": "<one sentence>"}}} '
        "with exactly the criteria listed above."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_judge_output(text: str, rubric: list[dict]) -> dict[str, dict]:
    """Parse and validate judge JSON. Raises JudgeParseError on any problem."""
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"not valid JSON: {exc.msg}") from exc
    scores = data.get("scores") if isinstance(data, dict) else None
    if not isinstance(scores, dict):
        raise JudgeParseError("missing 'scores' object")
    out: dict[str, dict] = {}
    for c in rubric:
        entry = scores.get(c["name"])
        if not isinstance(entry, dict):
            raise JudgeParseError(f"missing criterion '{c['name']}'")
        score = entry.get("score")
        if isinstance(score, float) and score.is_integer():
            score = int(score)
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            raise JudgeParseError(f"criterion '{c['name']}' has invalid score {score!r}")
        out[c["name"]] = {"score": score, "reason": str(entry.get("reason", ""))}
    return out


def normalize_scores(scores: dict[str, dict]) -> tuple[float, float]:
    """Return (mean raw 1..5, normalized 0..1 where 1 -> 0 and 5 -> 1)."""
    mean = sum(s["score"] for s in scores.values()) / len(scores)
    return mean, (mean - 1) / 4


async def _collect(client: OllamaClient, **kwargs) -> tuple[str, dict]:
    content, final = [], {}
    async for chunk in client.chat_stream(**kwargs):
        content.append(chunk.get("message", {}).get("content") or "")
        if chunk.get("done"):
            final = chunk
    return "".join(content), final


async def run_judge(
    client: OllamaClient,
    judge_model: str,
    call: JudgeCall,
    *,
    think: bool | None = False,
    attempts: int = 2,
    options: dict | None = None,
) -> tuple[ScoreResult, list[dict]]:
    """Judge one response. One retry on invalid output; `error` outcome (never raises) on failure.

    Returns (score, judge_call_metrics). Connection loss propagates so the caller can fail the run.
    """
    metrics: list[dict] = []
    last_error = "unknown"
    for attempt in range(1, attempts + 1):
        try:
            content, final = await _collect(
                client,
                model=judge_model,
                messages=build_judge_messages(call),
                options={"temperature": 0, "seed": 42, **(options or {})},
                think=think,
                format=rubric_schema(call.rubric),
            )
            metrics.append(
                {k: final.get(k) for k in ("total_duration", "eval_count", "eval_duration", "load_duration")}
            )
            scores = parse_judge_output(content, call.rubric)
        except OllamaUnreachable:
            raise
        except (JudgeParseError, OllamaError) as exc:
            last_error = str(exc)
            continue
        raw_mean, norm = normalize_scores(scores)
        return (
            ScoreResult(
                call.kind,
                norm,
                "judged",
                {
                    "criteria": scores,
                    "raw_mean": raw_mean,
                    "judge_model": judge_model,
                    "attempts": attempt,
                    **call.extra,
                },
            ),
            metrics,
        )
    return (
        ScoreResult(
            call.kind,
            None,
            "error",
            {"error": last_error, "judge_model": judge_model, "attempts": attempts, **call.extra},
        ),
        metrics,
    )
