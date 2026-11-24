"""Fresh actor, run, capability and target authority are independent admission fences."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
)
from app.core.config import settings
from app.core.permissions import AuthContext
from app.services.browser_procedure_teaching import _access
from app.services.browser_procedure_teaching._lease import BrowserProcedureTeachingIdentity
from tests.test_browser_procedure_teaching_native import identity

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ENDPOINT = "http://owned-browser:9222"


def spec(**changes):
    config = {
        "connection": "built_in",
        "cdp_url": ENDPOINT,
        "allow_teaching": True,
        "learn_site_procedures": True,
    }
    config.update(changes)
    return {"name": "Synthetic browser", "capabilities": [{"id": "browser_use", "config": config}]}


@pytest.fixture
def authority(monkeypatch):
    held = identity()
    ident = BrowserProcedureTeachingIdentity.model_validate(
        held.model_dump(exclude={"connection_id", "takeover_id"})
    )
    ctx = AuthContext(user_id=held.user_id, organization_id=held.organization_id, role="owner")
    run = SimpleNamespace(
        id=held.run_id,
        organization_id=held.organization_id,
        user_id=held.user_id,
        agent_id=held.agent_id,
        status="running",
        surface="web",
        initiated_by_publisher_fallback=False,
        key_scopes=None,
        parent_run_id=None,
        trigger_id=None,
        routine_origin_id=None,
        system_role=None,
        conversation_id=uuid4(),
        agent_version_id=uuid4(),
        test_spec=None,
    )
    agent = SimpleNamespace(
        id=held.agent_id, status="active", current_version_id=uuid4(), draft_spec=spec()
    )
    db = AsyncMock()
    person = AsyncMock(return_value=ctx)
    monkeypatch.setattr(_access, "person", person)
    monkeypatch.setattr(_access.run_repo, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(_access.agent_repo, "get", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        _access.agent_repo,
        "get_version",
        AsyncMock(return_value=SimpleNamespace(agent_id=held.agent_id, spec=spec())),
    )
    monkeypatch.setattr(_access.private_repo, "private_conversation", AsyncMock(return_value=True))
    monkeypatch.setattr(_access, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", ENDPOINT)
    policy = SimpleNamespace(enabled=True, generation=uuid4())
    monkeypatch.setattr(_access, "enabled", AsyncMock(return_value=policy))
    return SimpleNamespace(
        identity=ident, context=ctx, run=run, agent=agent, db=db, person=person, policy=policy
    )


@pytest.mark.parametrize(
    "field",
    [
        "missing_run",
        "user_id",
        "agent_id",
        "surface",
        "initiated_by_publisher_fallback",
        "key_scopes",
        "parent_run_id",
        "trigger_id",
        "routine_origin_id",
        "system_role",
        "conversation_id",
        "private",
        "status",
    ],
)
async def test_non_private_or_other_principal_run_is_never_admitted(authority, field):
    a = authority
    if field == "missing_run":
        _access.run_repo.get_run.return_value = None
    elif field == "private":
        _access.private_repo.private_conversation.return_value = False
    else:
        value = {
            "surface": "api",
            "status": "completed",
            "initiated_by_publisher_fallback": True,
            "key_scopes": ["runs:view"],
            "system_role": "system",
            "conversation_id": None,
        }.get(field, uuid4())
        setattr(a.run, field, value)
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _access.current_run(a.db, a.context, a.identity, live=True)
    assert caught.value.reason == BrowserProcedureTeachingReason.UNAVAILABLE
    _access.agent_repo.get.assert_not_awaited()


@pytest.mark.parametrize("field", ["user_id", "organization_id"])
async def test_actor_and_organization_must_match_the_server_identity(authority, field):
    a = authority
    changed = a.identity.model_copy(update={field: uuid4()})
    with pytest.raises(BrowserProcedureTeachingRefused):
        await _access.current_run(a.db, a.context, changed, live=True)
    _access.run_repo.get_run.assert_not_awaited()


@pytest.mark.parametrize("change", ["missing", "archived", "grant"])
async def test_agent_deletion_archival_or_grant_loss_is_checked_again(authority, change):
    a = authority
    if change == "missing":
        _access.agent_repo.get.return_value = None
    elif change == "archived":
        a.agent.status = "archived"
    else:
        _access.resolve_access.return_value = False
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _access.current_run(a.db, a.context, a.identity, live=True)
    assert caught.value.reason == BrowserProcedureTeachingReason.AUTHORITY_CHANGED


@pytest.mark.parametrize(
    "change",
    [
        "missing_frozen",
        "wrong_frozen",
        "missing_current",
        "wrong_current",
        "invalid_frozen",
        "invalid_current",
    ],
)
async def test_both_exact_frozen_and_current_published_specs_must_exist(authority, change):
    a = authority
    frozen = SimpleNamespace(agent_id=a.agent.id, spec=spec())
    current = SimpleNamespace(agent_id=a.agent.id, spec=spec())
    if change == "missing_frozen":
        a.run.agent_version_id = None
        _access.agent_repo.get_version.side_effect = [current]
    elif change == "missing_current":
        a.agent.current_version_id = None
        _access.agent_repo.get_version.side_effect = [frozen]
    else:
        changed = frozen if change.endswith("frozen") else current
        if change.startswith("wrong"):
            changed.agent_id = uuid4()
        else:
            changed.spec = "invalid spec"
        _access.agent_repo.get_version.side_effect = [frozen, current]
    with pytest.raises(BrowserProcedureTeachingRefused):
        await _access.specifications(a.db, a.run, a.agent)


async def test_manual_draft_run_uses_both_frozen_test_spec_and_current_draft(authority):
    a = authority
    a.run.test_spec = spec()
    old, current = await _access.specifications(a.db, a.run, a.agent)
    assert old.name == current.name == "Synthetic browser"
    _access.agent_repo.get_version.assert_not_awaited()


@pytest.mark.parametrize(
    "config",
    [
        None,
        {},
        {"name": "No browser"},
        {
            "name": "Invalid browser",
            "capabilities": [{"id": "browser_use", "config": {"max_steps": -1}}],
        },
    ],
)
async def test_missing_or_malformed_capability_is_a_fixed_refusal(authority, config):
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        _access._configuration(config)
    assert caught.value.reason == BrowserProcedureTeachingReason.UNAVAILABLE


@pytest.mark.parametrize("change", ["unprovisioned", "different", "connection"])
async def test_learning_never_uses_an_author_supplied_browser_endpoint(
    authority, monkeypatch, change
):
    raw = spec()
    if change == "unprovisioned":
        monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "")
    elif change == "different":
        raw = spec(cdp_url="http://another-browser:9222")
    else:
        raw = spec(connection="custom")
    with pytest.raises(BrowserProcedureTeachingRefused):
        _access._configuration(raw)


async def test_disabling_capture_in_current_publication_refuses_even_an_existing_run(authority):
    a = authority
    _access.agent_repo.get_version.side_effect = [
        SimpleNamespace(agent_id=a.agent.id, spec=spec()),
        SimpleNamespace(
            agent_id=a.agent.id, spec=spec(allow_teaching=False, learn_site_procedures=False)
        ),
    ]
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _access.admit(a.db, a.context, a.identity, live=True)
    assert caught.value.reason == BrowserProcedureTeachingReason.AUTHORITY_CHANGED


@pytest.mark.parametrize("exists", [False, True])
async def test_target_skill_must_be_current_and_editable(authority, monkeypatch, exists):
    a = authority
    skill = SimpleNamespace(id=uuid4()) if exists else None
    monkeypatch.setattr(_access.skill_repo, "get", AsyncMock(return_value=skill))
    _access.resolve_access.return_value = False
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _access.target(a.db, a.context, uuid4())
    assert caught.value.reason == BrowserProcedureTeachingReason.AUTHORITY_CHANGED
    _access.resolve_access.return_value = True
    if exists:
        assert await _access.target(a.db, a.context, skill.id) is skill


async def test_new_skill_needs_current_creation_permission(authority):
    a = authority
    denied = SimpleNamespace(organization_id=a.context.organization_id, has=lambda _: False)
    with pytest.raises(BrowserProcedureTeachingRefused):
        await _access.target(a.db, denied, None)


@pytest.mark.parametrize("change", ["anonymous", "key", "impersonated", "removed"])
async def test_person_lookup_never_uses_a_key_publisher_or_removed_member(monkeypatch, change):
    ctx = SimpleNamespace(
        personal_user_id=None if change == "anonymous" else uuid4(),
        api_key_id=uuid4() if change == "key" else None,
        organization_id=uuid4(),
    )
    monkeypatch.setattr(
        _access, "current_impersonator", lambda: uuid4() if change == "impersonated" else None
    )
    member = AsyncMock(return_value=None)
    monkeypatch.setattr(_access, "member_context", member)
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await _access.person(AsyncMock(), ctx)
    assert caught.value.reason == BrowserProcedureTeachingReason.UNAVAILABLE
    assert member.await_count == (1 if change == "removed" else 0)
