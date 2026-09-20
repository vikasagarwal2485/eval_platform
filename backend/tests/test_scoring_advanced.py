import json

import pytest

from app.core.scoring.aggregate import ScoredItem, category_scores, composite_score
from app.core.scoring.constraints import check_constraints, word_count
from app.core.scoring.judge import (
    JudgeCall,
    JudgeParseError,
    build_judge_messages,
    normalize_scores,
    parse_judge_output,
    run_judge,
)
from tests.fakes import FakeOllama, make_stream

RUBRIC = [{"name": "Relevance", "description": "on topic"}, {"name": "Fluency", "description": ""}]


def judge_json(a=4, b=5):
    return json.dumps({"scores": {"Relevance": {"score": a, "reason": "ok"}, "Fluency": {"score": b, "reason": "ok"}}})


# ------------------------------------------------------------------ 5.6 constraints
def test_max_words_violation_fails():
    text = " ".join(["word"] * 80)
    r = check_constraints(text, {"max_words": 50})
    assert r.outcome == "fail" and r.value == 0.0
    assert r.detail["checks"][0] == {"name": "max_words", "limit": 50, "actual": 80, "passed": False}


def test_constraints_pass_and_keywords():
    r = check_constraints(
        "A cold bottle, always.", {"max_words": 10, "required_keywords": ["COLD"], "forbidden_keywords": ["hot"]}
    )
    assert r.outcome == "pass" and all(c["passed"] for c in r.detail["checks"])


def test_forbidden_and_required_failures():
    r = check_constraints("hot drink", {"required_keywords": ["cold"], "forbidden_keywords": ["hot"]})
    assert r.outcome == "fail" and [c["passed"] for c in r.detail["checks"]] == [False, False]


def test_min_words_and_no_constraints():
    assert check_constraints("one two", {"min_words": 5}).outcome == "fail"
    assert check_constraints("anything", None) is None
    assert check_constraints("anything", {}) is None


def test_word_count():
    assert word_count("Don't stop-believing, 3 times!") == 4


# ------------------------------------------------------------------ 5.7 judge
def test_parse_and_normalize():
    scores = parse_judge_output(judge_json(4, 5), RUBRIC)
    mean, norm = normalize_scores(scores)
    assert mean == 4.5 and norm == pytest.approx(0.875)
    assert normalize_scores(parse_judge_output(judge_json(1, 1), RUBRIC))[1] == 0.0
    assert normalize_scores(parse_judge_output(judge_json(5, 5), RUBRIC))[1] == 1.0


def test_parse_accepts_code_fences_and_rejects_bad():
    assert parse_judge_output("```json\n" + judge_json() + "\n```", RUBRIC)
    for bad in [
        "nope",
        "{}",
        json.dumps({"scores": {"Relevance": {"score": 3, "reason": ""}}}),
        judge_json(0, 3),
        judge_json(6, 3),
        json.dumps({"scores": {"Relevance": {"score": "high"}, "Fluency": {"score": 3}}}),
    ]:
        with pytest.raises(JudgeParseError):
            parse_judge_output(bad, RUBRIC)


def test_judge_prompt_contains_task_response_and_criteria():
    msgs = build_judge_messages(JudgeCall(task="Write a haiku", response="Old pond...", rubric=RUBRIC))
    body = msgs[1]["content"]
    assert "Write a haiku" in body and "Old pond" in body and "Relevance" in body and "Fluency" in body


def call():
    return JudgeCall(task="t", response="r", rubric=RUBRIC)


async def test_judge_valid_response():
    fake = FakeOllama(responder=lambda m, msgs, o: make_stream(judge_json(4, 4)))
    res, metrics = await run_judge(fake, "judge:1", call())
    assert res.outcome == "judged" and res.value == pytest.approx(0.75)
    assert res.detail["criteria"]["Relevance"]["score"] == 4 and res.detail["attempts"] == 1
    assert len(metrics) == 1
    chat_call = fake.calls[0]
    assert chat_call[2]["temperature"] == 0 and chat_call[3] is False  # options, think off
    assert chat_call[4]["type"] == "object"  # JSON-schema `format`


async def test_judge_invalid_then_valid_retries_once():
    replies = iter(["I think it is good", judge_json(5, 5)])
    fake = FakeOllama(responder=lambda m, msgs, o: make_stream(next(replies)))
    res, metrics = await run_judge(fake, "j", call())
    assert res.outcome == "judged" and res.value == 1.0 and res.detail["attempts"] == 2
    assert len(metrics) == 2


async def test_judge_always_invalid_is_error_not_exception():
    fake = FakeOllama(responder=lambda m, msgs, o: make_stream("garbage"))
    res, _ = await run_judge(fake, "j", call())
    assert res.outcome == "error" and res.value is None and "JSON" in res.detail["error"]
    assert sum(1 for c in fake.calls if c[0] == "chat") == 2  # exactly one retry


async def test_judge_connection_loss_propagates():
    from app.ollama.client import OllamaUnreachable

    with pytest.raises(OllamaUnreachable):
        await run_judge(FakeOllama(down=True), "j", call())


# ------------------------------------------------------------------ 5.8 aggregation
def I(model, case, cat, value, outcome=""):
    return ScoredItem(model, case, cat, value, outcome)


def test_category_scores_average_repeats_then_cases():
    items = [
        I(1, 10, "classification", 1.0),
        I(1, 10, "classification", 0.0),  # case 10 -> 0.5
        I(1, 11, "classification", 1.0),  # case 11 -> 1.0
    ]
    c = category_scores(items)[1]["classification"]
    assert c["score"] == pytest.approx(0.75) and c["scored"] == 2 and c["total"] == 2


def test_unscored_cases_excluded_from_mean_but_counted():
    items = [I(1, 1, "generation", 0.5), I(1, 2, "generation", None, "unscored")]
    g = category_scores(items)[1]["generation"]
    assert g["score"] == 0.5 and g["scored"] == 1 and g["total"] == 2


def test_all_unscored_gives_none():
    assert category_scores([I(1, 1, "generation", None)])[1]["generation"]["score"] is None


def test_error_and_unparseable_counts():
    items = [
        I(1, 1, "reasoning", 0.0, "error"),
        I(1, 2, "reasoning", 0.0, "unparseable"),
        I(1, 3, "reasoning", 1.0, "correct"),
    ]
    r = category_scores(items)[1]["reasoning"]
    assert (r["errors"], r["unparseable"], r["score"]) == (1, 1, pytest.approx(1 / 3))


def test_composite_with_weights():
    cs = {"classification": {"score": 1.0}, "reasoning": {"score": 0.5}, "generation": {"score": 0.0}}
    assert composite_score(cs, {"classification": 0.4, "reasoning": 0.4, "generation": 0.2}) == pytest.approx(0.6)
    assert composite_score(cs) == pytest.approx(0.5)  # equal default weights
    assert composite_score(cs, {"classification": 1, "reasoning": 0, "generation": 0}) == 1.0


def test_composite_renormalizes_when_category_missing():
    """Run with no reasoning cases: reasoning weight is dropped, not counted as 0."""
    cs = {"classification": {"score": 1.0}, "generation": {"score": 0.5}}
    w = {"classification": 0.4, "reasoning": 0.4, "generation": 0.2}
    assert composite_score(cs, w) == pytest.approx((0.4 * 1.0 + 0.2 * 0.5) / 0.6)


def test_composite_skips_unscored_categories_and_handles_none():
    assert composite_score({"generation": {"score": None}}) is None
    assert composite_score({"classification": {"score": 0.8}, "generation": {"score": None}}) == 0.8
    assert composite_score({}) is None
