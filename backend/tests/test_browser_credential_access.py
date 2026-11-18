"""Admission decisions use trusted private-run provenance and current named authority."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.spec import AgentSpec
from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from app.core.config import settings
from app.core.permissions import AuthContext
from app.services.browser_credentials import _access
from tests.test_browser_credential_lease import identity

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ENDPOINT = "http://provisioned-browser:9222"


@pytest.fixture
def access(monkeypatch: pytest.MonkeyPatch):
    native = identity()
    ctx = AuthContext(user_id=native.user_id, organization_id=native.organization_id, role="owner")
    version_id = uuid4()
    spec = AgentSpec.model_validate(
        {
            "name": "Synthetic browser",
            "capabilities": [
                {
                    "id": "browser_use",
                    "config": {
                        "connection": "built_in",
                        "cdp_url": ENDPOINT,
                        "browser_credential_ids": list(native.credential_ids),
                    },
                }
            ],
        }
    ).model_dump(mode="json")
    run = SimpleNamespace(
        organization_id=native.organization_id,
        id=native.run_id,
        agent_id=native.agent_id,
        user_id=native.user_id,
        status="running",
        surface="web",
        initiated_by_publisher_fallback=False,
        key_scopes=None,
        parent_run_id=None,
        trigger_id=None,
        routine_origin_id=None,
        system_role=None,
        conversation_id=uuid4(),
        test_spec=None,
        agent_version_id=version_id,
    )
    agent = SimpleNamespace(
        id=native.agent_id, status="published", current_version_id=version_id, draft_spec=spec
    )
    version = SimpleNamespace(
        id=version_id, agent_id=native.agent_id, organization_id=native.organization_id, spec=spec
    )
    secret = SimpleNamespace(
        id=native.credential_ids[0],
        organization_id=native.organization_id,
        owner_user_id=native.user_id,
        kind="browser_login",
        visibility="private",
        usage_scope="personal",
        authorization_generation=uuid4(),
    )
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", ENDPOINT)
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_FILL_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_ORGANIZATION_IDS", [native.organization_id])
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_USER_IDS", [native.user_id])
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_SHARED_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_PROFILE_ENABLED", True)
    monkeypatch.setattr(_access, "current_impersonator", lambda: None)
    monkeypatch.setattr(_access, "member_context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(_access.run_repo, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(_access.agent_repo, "get", AsyncMock(return_value=agent))
    monkeypatch.setattr(_access.agent_repo, "get_version", AsyncMock(return_value=version))
    monkeypatch.setattr(_access.repo, "private_conversation", AsyncMock(return_value=True))
    monkeypatch.setattr(_access, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(_access.repo, "secret", AsyncMock(return_value=secret))
    monkeypatch.setattr(_access.repo, "granted", AsyncMock(return_value=True))
    monkeypatch.setattr(_access.member_repo, "get_active", AsyncMock(return_value=object()))
    return SimpleNamespace(
        db=AsyncMock(),
        identity=native,
        ctx=ctx,
        run=run,
        agent=agent,
        version=version,
        secret=secret,
        spec=spec,
    )


async def test_private_run_and_test_draft_use_frozen_ids_and_current_subtractive_binding(
    access,
) -> None:
    a = access
    assert await _access.private_run(a.db, a.ctx, a.identity) == (a.ctx, a.run)
    a.run.test_spec = a.spec
    assert await _access.bound_ids(a.db, a.run) == a.identity.credential_ids
    assert await _access.private_run(a.db, a.ctx, a.identity) == (a.ctx, a.run)
    a.agent.draft_spec = AgentSpec(name="Withdrawn").model_dump(mode="json")
    with pytest.raises(BrowserFillRefused):
        await _access.private_run(a.db, a.ctx, a.identity)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "completed"),
        ("user_id", "uuid"),
        ("agent_id", "uuid"),
        ("surface", "api"),
        ("initiated_by_publisher_fallback", True),
        ("key_scopes", []),
        ("parent_run_id", "uuid"),
        ("trigger_id", "uuid"),
        ("routine_origin_id", "uuid"),
        ("system_role", "room-lead"),
        ("conversation_id", None),
    ],
)
async def test_nonprivate_or_delegated_run_provenance_refuses_before_credential_lookup(
    access, field, value
) -> None:
    a = access
    setattr(a.run, field, uuid4() if value == "uuid" else value)
    with pytest.raises(BrowserFillRefused):
        await _access.private_run(a.db, a.ctx, a.identity)
    _access.repo.secret.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [
        "missing_run",
        "shared_conversation",
        "missing_agent",
        "archived_agent",
        "agent_access",
        "binding_mismatch",
        "current_binding_revoked",
        "missing_current_version",
        "foreign_current_version",
    ],
)
async def test_current_authority_is_rechecked_for_every_plan_step(access, failure) -> None:
    a = access
    if failure == "missing_run":
        _access.run_repo.get_run.return_value = None
    elif failure == "shared_conversation":
        _access.repo.private_conversation.return_value = False
    elif failure == "missing_agent":
        _access.agent_repo.get.return_value = None
    elif failure == "archived_agent":
        a.agent.status = "archived"
    elif failure == "agent_access":
        _access.resolve_access.return_value = False
    elif failure == "binding_mismatch":
        a.identity = a.identity.model_copy(update={"credential_ids": (uuid4(),)})
    elif failure == "current_binding_revoked":
        current = SimpleNamespace(
            agent_id=a.agent.id,
            spec=AgentSpec(
                name="Revoked",
                capabilities=[
                    {
                        "id": "browser_use",
                        "config": {"connection": "built_in", "cdp_url": ENDPOINT},
                    }
                ],
            ).model_dump(mode="json"),
        )
        _access.agent_repo.get_version.side_effect = [a.version, current]
    elif failure == "missing_current_version":
        a.agent.current_version_id = None
    else:
        _access.agent_repo.get_version.side_effect = [
            a.version,
            SimpleNamespace(agent_id=uuid4(), spec=a.spec),
        ]
    with pytest.raises(BrowserFillRefused):
        await _access.private_run(a.db, a.ctx, a.identity)


@pytest.mark.parametrize("field", ["user_id", "organization_id"])
async def test_person_context_cannot_cross_controller_authority(access, field) -> None:
    a = access
    _access.member_context.return_value = replace(a.ctx, **{field: uuid4()})
    with pytest.raises(BrowserFillRefused):
        await _access.private_run(a.db, a.ctx, a.identity)


@pytest.mark.parametrize(
    "override",
    [
        {"user_id": None},
        {"api_key_id": "uuid"},
        {"subject_is_publisher_fallback": True},
        {"is_impersonated": True},
        {"is_workflow": True},
    ],
)
async def test_nonpersonal_subjects_never_gain_vault_authority(access, override) -> None:
    ctx = replace(
        access.ctx,
        **{key: uuid4() if value == "uuid" else value for key, value in override.items()},
    )
    with pytest.raises(BrowserFillRefused):
        await _access.person(access.db, ctx)
    _access.member_context.assert_not_awaited()


async def test_removed_member_and_active_impersonator_are_refused(
    access, monkeypatch: pytest.MonkeyPatch
) -> None:
    _access.member_context.return_value = None
    with pytest.raises(BrowserFillRefused):
        await _access.person(access.db, access.ctx)
    monkeypatch.setattr(_access, "current_impersonator", lambda: uuid4())
    with pytest.raises(BrowserFillRefused):
        await _access.person(access.db, access.ctx)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("BROWSER_CREDENTIAL_FILL_ENABLED", False),
        ("BROWSER_CREDENTIAL_ORGANIZATION_IDS", []),
        ("BROWSER_CREDENTIAL_USER_IDS", [uuid4()]),
    ],
)
async def test_deployment_admission_is_default_closed_and_explicitly_scoped(
    access, monkeypatch, flag, value
) -> None:
    monkeypatch.setattr(settings, flag, value)
    with pytest.raises(BrowserFillRefused) as caught:
        _access.enabled(access.identity.organization_id, access.identity.user_id)
    assert caught.value.reason == BrowserFillReason.DISABLED


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"name": "No browser"},
        {"name": "Disabled", "capabilities": [{"id": "browser_use", "enabled": False}]},
    ],
)
async def test_missing_or_invalid_frozen_spec_is_refused(access, raw) -> None:
    with pytest.raises(BrowserFillRefused):
        _access.configured_ids(raw)


@pytest.mark.parametrize(
    "change", ["bad_config", "external", "different_endpoint", "no_provisioned_endpoint"]
)
async def test_only_the_provisioned_native_browser_may_bind_saved_credentials(
    access, change, monkeypatch
) -> None:
    raw = dict(access.spec)
    config = dict(raw["capabilities"][0]["config"])
    if change == "bad_config":
        config["browser_credential_ids"] = ["invalid"]
    elif change == "external":
        config["connection"] = "hosted"
    elif change == "different_endpoint":
        config["cdp_url"] = "http://another-browser:9222"
    else:
        monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "")
    raw["capabilities"] = [{"id": "browser_use", "config": config}]
    with pytest.raises(BrowserFillRefused):
        _access.configured_ids(raw)


@pytest.mark.parametrize("failure", ["missing_version", "foreign_version", "no_version"])
async def test_unrecoverable_run_version_cannot_borrow_a_new_draft(access, failure) -> None:
    if failure == "missing_version":
        _access.agent_repo.get_version.return_value = None
    elif failure == "foreign_version":
        access.version.agent_id = uuid4()
    else:
        access.run.agent_version_id = None
    with pytest.raises(BrowserFillRefused):
        await _access.bound_ids(access.db, access.run)


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "wrong_kind",
        "no_owner",
        "public",
        "generation",
        "not_personal",
        "other_owner",
        "denied",
        "unknown_scope",
        "shared_disabled",
        "shared_owner_removed",
        "shared_ungranted",
        "profile_disabled",
    ],
)
async def test_credential_lookup_refuses_without_metadata_or_value(
    access, failure, monkeypatch
) -> None:
    a = access
    ctx = a.ctx
    generation = a.secret.authorization_generation
    if failure == "missing":
        _access.repo.secret.return_value = None
    elif failure == "wrong_kind":
        a.secret.kind = "api_key"
    elif failure == "no_owner":
        a.secret.owner_user_id = None
    elif failure == "public":
        a.secret.visibility = "org"
    elif failure == "generation":
        generation = uuid4()
    elif failure == "not_personal":
        ctx = replace(ctx, user_id=None)
    elif failure == "other_owner":
        a.secret.owner_user_id = uuid4()
    elif failure == "denied":
        _access.resolve_access.return_value = False
    elif failure == "unknown_scope":
        a.secret.usage_scope = "unknown"
    elif failure == "profile_disabled":
        a.secret.kind = "browser_profile"
        monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_PROFILE_ENABLED", False)
    else:
        a.secret.usage_scope = "organization"
        if failure == "shared_disabled":
            monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_SHARED_ENABLED", False)
        elif failure == "shared_owner_removed":
            _access.member_repo.get_active.return_value = None
        else:
            _access.repo.granted.return_value = False
    with pytest.raises(BrowserFillRefused):
        await _access.credential(
            a.db,
            ctx,
            secret_id=a.secret.id,
            agent_id=a.agent.id,
            generation=generation,
            locked=True,
        )


async def test_personal_and_explicit_shared_credentials_are_returned_only_after_gates(
    access,
) -> None:
    a = access
    assert (
        await _access.credential(a.db, a.ctx, secret_id=a.secret.id, agent_id=a.agent.id)
        is a.secret
    )
    a.secret.usage_scope = "organization"
    assert (
        await _access.credential(a.db, a.ctx, secret_id=a.secret.id, agent_id=a.agent.id)
        is a.secret
    )
