from app.core.eligibility import plan_turn_evaluators, same_family, same_model


def test_same_model_identical_local_names():
    assert same_model("qwen3:8b", "qwen3:8b")


def test_same_model_differing_tags_same_digest():
    digests = {"qwen3:8b": "sha256:abc", "qwen3:latest": "sha256:abc"}
    assert same_model("qwen3:8b", "qwen3:latest", digest_of=digests.get)


def test_same_model_differing_tags_different_digest():
    digests = {"qwen3:8b": "sha256:abc", "qwen3:32b": "sha256:def"}
    assert not same_model("qwen3:8b", "qwen3:32b", digest_of=digests.get)


def test_same_model_two_cloud_refs_same_provider_and_model():
    assert same_model("@openai-main/gpt-4o", "@openai-main/gpt-4o")


def test_same_model_two_cloud_refs_different_provider():
    assert not same_model("@openai-main/gpt-4o", "@openai-backup/gpt-4o")


def test_same_model_cloud_never_matches_by_digest():
    assert not same_model("@openai-main/gpt-4o", "@openai-main/gpt-4o-mini", digest_of=lambda _: "same")


def test_same_family_flags_different_sizes():
    assert same_family("qwen3:8b", "qwen3:32b")
    assert not same_family("qwen3:8b", "qwen3:8b")  # identical, not "same family different model"
    assert not same_family("qwen3:8b", "gemma3:4b")


def test_plan_two_eligible_evaluators():
    plan = plan_turn_evaluators(["B", "C"], ["A"])
    assert plan.eligible == ["B", "C"]
    assert plan.skip_reason is None


def test_plan_excludes_author_only_for_that_turn():
    plan = plan_turn_evaluators(["A", "B"], ["A"])
    assert plan.eligible == ["B"]


def test_plan_no_eligible_evaluator():
    plan = plan_turn_evaluators(["A"], ["A"])
    assert plan.eligible == []
    assert plan.skip_reason == "no_eligible_evaluator"


def test_plan_models_unknown():
    plan = plan_turn_evaluators(["A", "B"], [], models_unknown=True)
    assert plan.eligible == []
    assert plan.skip_reason == "agent_model_unknown"


def test_plan_empty_turn_models_is_unknown_even_without_the_flag():
    plan = plan_turn_evaluators(["A", "B"], [])
    assert plan.skip_reason == "agent_model_unknown"


def test_plan_flags_same_family():
    plan = plan_turn_evaluators(["qwen3:32b"], ["qwen3:8b"])
    assert plan.eligible == ["qwen3:32b"]
    assert plan.same_family == ["qwen3:32b"]
