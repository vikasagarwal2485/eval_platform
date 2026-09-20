"""3.1: who judges what."""

from app.core.scoring.judging import JudgeTarget, plan_judgements

A, B, C = (1, "a:1"), (2, "b:1"), (3, "c:1")


def T(result_id, author, kind="judge"):
    return JudgeTarget(result_id, author[0], kind)


def by_result(tasks):
    out = {}
    for t in tasks:
        out.setdefault(t.result_id, []).append(t.judge_model)
    return out


def test_two_models_judge_each_other_and_never_themselves():
    tasks = plan_judgements("cross_model", None, [A, B], [T(10, A), T(11, B), T(12, A)])
    assert by_result(tasks) == {10: ["b:1"], 11: ["a:1"], 12: ["b:1"]}


def test_three_models_each_answer_gets_the_two_others():
    tasks = plan_judgements("cross_model", None, [A, B, C], [T(10, A), T(11, B), T(12, C)])
    assert {k: sorted(v) for k, v in by_result(tasks).items()} == {
        10: ["b:1", "c:1"],
        11: ["a:1", "c:1"],
        12: ["a:1", "b:1"],
    }
    assert len(tasks) == 3 * 2  # answers x (models - 1)


def test_invariant_no_task_pairs_an_answer_with_its_author():
    models = [(i, f"m{i}:1") for i in range(1, 7)]
    targets = [T(100 + i, m) for i, m in enumerate(models)] * 2
    for t in plan_judgements("cross_model", None, models, targets):
        assert t.judge_model != dict((i, n) for i, n in models)[t.author_id]


def test_tasks_are_grouped_by_judge_in_run_order():
    tasks = plan_judgements("cross_model", None, [A, B, C], [T(10, A), T(11, B), T(12, C), T(13, A)])
    judges = [t.judge_model for t in tasks]
    # contiguous groups, in run-model order: a:1's judgements, then b:1's, then c:1's
    assert judges == sorted(judges)
    assert [j for i, j in enumerate(judges) if i == 0 or judges[i - 1] != j] == ["a:1", "b:1", "c:1"]


def test_authors_are_matched_by_snapshot_id_not_by_name():
    """Two builds of the same tag are different models: they judge each other."""
    old, new = (1, "a:1"), (2, "a:1")
    tasks = plan_judgements("cross_model", None, [old, new], [T(10, old), T(11, new)])
    # by name both judges are "a:1", yet each answer still gets exactly one judge: the *other* snapshot
    assert sorted((t.result_id, t.author_id, t.judge_model) for t in tasks) == [(10, 1, "a:1"), (11, 2, "a:1")]
    assert len(tasks) == 2


def test_reasoning_quality_targets_follow_the_same_rule():
    tasks = plan_judgements("cross_model", None, [A, B], [T(10, A, "judge_reasoning"), T(11, B, "judge")])
    assert [(t.result_id, t.judge_model, t.kind) for t in tasks] == [
        (11, "a:1", "judge"),
        (10, "b:1", "judge_reasoning"),
    ]


def test_single_mode_uses_one_judge_even_if_it_is_the_author():
    tasks = plan_judgements("single", "a:1", [A, B], [T(10, A), T(11, B)])
    assert [(t.result_id, t.judge_model) for t in tasks] == [(10, "a:1"), (11, "a:1")]


def test_none_and_missing_judge_plan_nothing():
    assert plan_judgements("none", None, [A, B], [T(10, A)]) == []
    assert plan_judgements("single", None, [A, B], [T(10, A)]) == []
    assert plan_judgements("cross_model", None, [A, B], []) == []
    assert plan_judgements("cross_model", None, [A], [T(10, A)]) == []  # a lone model has no peers
