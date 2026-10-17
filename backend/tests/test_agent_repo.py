import pytest
from pydantic import ValidationError

from app import repo
from app.repo import AckRequired, Conflict
from app.schemas import AgentSettingsUpdate, EvalConfigIn


def _create(session, name="bot", evaluators=None, declared="qwen3:8b", acks=None):
    declared_models = declared if isinstance(declared, dict) else {"default": declared}
    return repo.create_agent(
        session,
        name=name,
        kind="chatbot",
        declared_models=declared_models,
        eval_config=EvalConfigIn(evaluators=evaluators or []),
        rubric=None,
        provider_acks=acks or [],
    )


def test_create_agent_issues_a_token_shown_only_once(session):
    agent, raw = _create(session)
    assert agent.token_prefix == raw[:8]
    assert agent.token_hash != raw
    assert raw not in agent.token_hash


def test_duplicate_name_rejected(session):
    _create(session, name="bot")
    with pytest.raises(Conflict):
        _create(session, name="bot")


def test_defaults_apply_when_eval_config_unset(session):
    agent, _ = _create(session)
    assert agent.eval_config["sample_rate"] == 1.0
    assert agent.eval_config["quiet_period_s"] == 20.0


def test_invalid_sample_rate_rejected():
    with pytest.raises(ValidationError):
        EvalConfigIn(sample_rate=1.5)


def test_self_evaluator_rejected_at_create(session):
    with pytest.raises(ValueError):
        _create(session, evaluators=["qwen3:8b"], declared="qwen3:8b")


def test_self_evaluator_rejected_at_update(session):
    agent, _ = _create(session)
    with pytest.raises(ValueError):
        repo.update_agent_settings(
            session, agent.id, AgentSettingsUpdate(eval_config=EvalConfigIn(evaluators=["qwen3:8b"]))
        )


def test_declared_model_can_differ_from_evaluators(session):
    agent, _ = _create(session, evaluators=["gemma3:4b"], declared="qwen3:8b")
    assert agent.eval_config["evaluators"] == ["gemma3:4b"]


def test_self_evaluator_rejected_when_it_matches_any_of_several_declared_models(session):
    """task 3.1/3.3: _check_no_self_evaluator loops over every declared model, not just one."""
    with pytest.raises(ValueError, match="gemma3:4b"):
        _create(session, evaluators=["gemma3:4b"], declared={"reasoning": "qwen3:8b", "generation": "gemma3:4b"})


def test_evaluator_matching_neither_declared_model_is_accepted(session):
    """task 3.2: 'An evaluator distinct from every declared model is accepted'."""
    agent, _ = _create(session, evaluators=["judge:1"], declared={"reasoning": "qwen3:8b", "generation": "gemma3:4b"})
    assert agent.eval_config["evaluators"] == ["judge:1"]


def test_hosted_evaluator_requires_acknowledgment(session):
    with pytest.raises(AckRequired):
        _create(session, evaluators=["@openai-main/gpt-4o"])


def test_acknowledgment_recorded_and_not_required_again(session):
    agent, _ = _create(session, evaluators=["@openai-main/gpt-4o"], acks=["openai-main"])
    assert "openai-main" in agent.provider_acks
    # saving again with the same provider does not require re-acknowledging
    repo.update_agent_settings(
        session, agent.id, AgentSettingsUpdate(eval_config=EvalConfigIn(evaluators=["@openai-main/gpt-4o"]))
    )


def test_new_provider_requires_new_acknowledgment(session):
    agent, _ = _create(session, evaluators=["@openai-main/gpt-4o"], acks=["openai-main"])
    with pytest.raises(AckRequired):
        repo.update_agent_settings(
            session,
            agent.id,
            AgentSettingsUpdate(eval_config=EvalConfigIn(evaluators=["@openai-main/gpt-4o", "@anthropic-main/claude"])),
        )


def test_pause_rejects_and_resume_allows(session):
    agent, _ = _create(session)
    repo.set_agent_status(session, agent.id, "paused")
    assert repo.get_agent(session, agent.id).status == "paused"
    repo.set_agent_status(session, agent.id, "active")
    assert repo.get_agent(session, agent.id).status == "active"


def test_token_rotation_invalidates_the_old_token(session):
    agent, old_raw = _create(session)
    agent, new_raw = repo.rotate_agent_token(session, agent.id)
    assert repo.verify_agent_token(session, new_raw) is not None
    assert repo.verify_agent_token(session, old_raw) is None


def test_delete_agent_cascades(session):
    agent, _ = _create(session)
    sess = repo.get_or_create_agent_session(session, agent, "s1")
    repo.get_or_create_turn(session, agent, sess, "t1")
    session.commit()
    repo.delete_agent(session, agent.id)
    session.commit()
    with pytest.raises(repo.NotFound):
        repo.get_agent(session, agent.id)
