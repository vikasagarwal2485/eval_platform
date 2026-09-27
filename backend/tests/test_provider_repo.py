"""2.2: provider and registered-model persistence."""

from datetime import UTC, datetime

import pytest

from app import repo
from app.repo import CaseSource
from app.schemas import CaseIn, ModelInfo


def mk_provider(session, name="openai-main", kind="openai", key_env="OPENAI_API_KEY"):
    return repo.create_provider(session, kind=kind, name=name, key_env=key_env, base_url=None, ack_at=datetime.now(UTC))


def test_provider_names_are_unique(session):
    mk_provider(session)
    with pytest.raises(repo.Conflict, match="already exists"):
        mk_provider(session, key_env="OTHER")
    assert repo.get_provider_by_name(session, "openai-main").kind == "openai"
    assert repo.get_provider_by_name(session, "nope") is None


def test_two_providers_of_the_same_kind_are_allowed_under_different_names(session):
    mk_provider(session, "openai-a", key_env="A_KEY")
    mk_provider(session, "openai-b", key_env="B_KEY")
    assert [p.name for p in repo.list_providers(session)] == ["openai-a", "openai-b"]


def test_model_ids_are_unique_per_provider_only(session):
    a, b = mk_provider(session, "a"), mk_provider(session, "b")
    repo.add_registered_model(session, a.id, "gpt-4o")
    repo.add_registered_model(session, b.id, "gpt-4o")  # same id under another provider is fine
    with pytest.raises(repo.Conflict, match="already registered"):
        repo.add_registered_model(session, a.id, "gpt-4o")


def test_enable_disable_flag_and_listing(session):
    p = mk_provider(session)
    m1 = repo.add_registered_model(session, p.id, "gpt-4o")
    m2 = repo.add_registered_model(session, p.id, "o3", reasoning=True)
    repo.update_registered_model(session, m1.id, enabled=False)
    assert [m.model_id for m in repo.list_registered_models(session)] == ["gpt-4o", "o3"]
    assert [m.model_id for m in repo.list_registered_models(session, enabled_only=True)] == ["o3"]
    assert repo.get_registered_model(session, m2.id).reasoning is True
    repo.update_registered_model(session, m2.id, reasoning=False, display_name="O3")
    assert (
        repo.get_registered_model(session, m2.id).reasoning,
        repo.get_registered_model(session, m2.id).display_name,
    ) == (False, "O3")


def test_update_provider_changes_variable_and_base_url_but_never_the_name(session):
    p = mk_provider(session)
    repo.update_provider(session, p.id, key_env="NEW_KEY", base_url="https://gw.example/v1")
    p = repo.get_provider(session, p.id)
    assert (p.name, p.key_env, p.base_url) == ("openai-main", "NEW_KEY", "https://gw.example/v1")
    repo.update_provider(session, p.id, clear_base_url=True)
    assert repo.get_provider(session, p.id).base_url is None


def test_find_registered(session):
    p = mk_provider(session)
    m = repo.add_registered_model(session, p.id, "gpt-4o")
    assert repo.find_registered(session, "openai-main", "gpt-4o") == (p, m)
    assert repo.find_registered(session, "openai-main", "missing") == (p, None)
    assert repo.find_registered(session, "ghost", "gpt-4o") == (None, None)


def test_deleting_a_provider_cascades_to_its_models(session):
    p = mk_provider(session)
    repo.add_registered_model(session, p.id, "gpt-4o")
    repo.delete_provider(session, p.id)
    assert repo.list_providers(session) == [] and repo.list_registered_models(session) == []


def cloud_run(session, ref="@openai-main/gpt-4o", status="completed", judge=None):
    snap = repo.get_or_create_snapshot(
        session, ModelInfo(name=ref, digest="", source="cloud", provider="openai-main", provider_kind="openai")
    )
    run = repo.create_run(
        session,
        name="r",
        config={},
        judge_model=judge,
        snapshots=[snap],
        cases=[CaseSource(CaseIn(category="generation", prompt="x"))],
    )
    repo.set_run_status(session, run.id, status)
    return run, snap


def test_cloud_snapshot_records_source_and_provider_kind(session):
    _, snap = cloud_run(session)
    assert (snap.name, snap.digest, snap.source, snap.provider_kind) == ("@openai-main/gpt-4o", "", "cloud", "openai")
    local = repo.get_or_create_snapshot(session, ModelInfo(name="qwen3:8b", digest="d"))
    assert (local.source, local.provider_kind) == ("local", None)
    again = repo.get_or_create_snapshot(session, ModelInfo(name="@openai-main/gpt-4o", digest="", source="cloud"))
    assert again.id == snap.id  # reused, not duplicated


@pytest.mark.parametrize(
    "status,blocked",
    [("queued", True), ("running", True), ("completed", False), ("cancelled", False), ("failed", False)],
)
def test_provider_in_use_only_by_queued_or_running_runs(session, status, blocked):
    p = mk_provider(session)
    cloud_run(session, status=status)
    assert repo.provider_in_use(session, "openai-main") is blocked
    if blocked:
        with pytest.raises(repo.Conflict, match="queued or running"):
            repo.delete_provider(session, p.id)
        assert repo.get_provider(session, p.id)  # untouched
    else:
        repo.delete_provider(session, p.id)


def test_a_provider_used_only_as_judge_is_in_use(session):
    p = mk_provider(session)
    snap = repo.get_or_create_snapshot(session, ModelInfo(name="qwen3:8b", digest="d"))
    run = repo.create_run(
        session,
        name="r",
        config={},
        judge_model="@openai-main/gpt-4o",
        snapshots=[snap],
        cases=[CaseSource(CaseIn(category="generation", prompt="x"))],
    )
    repo.set_run_status(session, run.id, "running")
    assert repo.provider_in_use(session, "openai-main")
    with pytest.raises(repo.Conflict):
        repo.delete_provider(session, p.id)
    assert not repo.provider_in_use(session, "other")


def test_history_survives_removing_the_provider(session):
    p = mk_provider(session)
    repo.add_registered_model(session, p.id, "gpt-4o")
    run, snap = cloud_run(session)
    repo.delete_provider(session, p.id)
    session.expire_all()
    got = repo.get_run(session, run.id)
    assert [s.name for s in repo.run_snapshots(session, got)] == ["@openai-main/gpt-4o"]
    assert repo.run_snapshots(session, got)[0].source == "cloud"
