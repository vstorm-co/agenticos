"""Shared starts are independent of each member's completed personal onboarding."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.db.models.deployment_settings import DeploymentSettings
from app.repositories import (
    deployment_settings_repo,
    onboarding_repo,
    organization_repo,
    user_repo,
)
from app.schemas.onboarding import OnboardingScopeUpdate
from tests import test_onboarding as personal_cases
from tests.test_onboarding import StartFixture

start = personal_cases.start

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def shared_identity_boundary(start, monkeypatch):
    ctx, member, db, _ = start
    person = user_repo.get_by_id.return_value
    monkeypatch.setattr(
        onboarding_repo, "shared_identity", AsyncMock(return_value=(member, person))
    )
    monkeypatch.setattr(
        onboarding_repo, "deployment_actor", AsyncMock(side_effect=lambda _db, _id: person)
    )


async def test_shared_stages_do_not_inherit_completed_personal_progress(
    start: StartFixture, monkeypatch
):
    ctx, member, _, service = start
    member.onboarding_completed_at = datetime.now(UTC)
    person = await user_repo.get_by_id(service.db, member.user_id)
    person.is_app_admin = person.is_active = True
    result = await service.state(ctx)
    assert [scope.scope for scope in result.scopes] == ["deployment", "organization", "personal"]
    assert [scope.completed for scope in result.scopes] == [False, False, True]
    assert result.active_scope == "deployment"
    deployment = DeploymentSettings(onboarding_completed_at=datetime.now(UTC))
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=deployment))
    assert (await service.state(ctx)).active_scope == "organization"
    org = await organization_repo.get_by_id(service.db, ctx.organization_id)
    org.onboarding_completed_at = datetime.now(UTC)
    assert (await service.state(ctx)).active_scope is None


@pytest.mark.security
async def test_current_membership_and_admin_flag_override_stale_context(start: StartFixture):
    ctx, member, _, service = start
    member.role = "member"
    person = await user_repo.get_by_id(service.db, member.user_id)
    person.is_active = True
    stale = replace(ctx, is_app_admin=True)
    result = await service.state(stale)
    assert [scope.applicable for scope in result.scopes] == [False, False, True]
    for scope in ("deployment", "organization"):
        with pytest.raises(AuthorizationError):
            await service.update_scope(stale, scope, OnboardingScopeUpdate(completed=True))


@pytest.mark.security
@pytest.mark.parametrize("keyed", [True, False])
async def test_shared_setup_never_borrows_background_or_key_authority(start: StartFixture, keyed):
    from uuid import uuid4

    ctx, _, _, service = start
    person = await user_repo.get_by_id(service.db, ctx.subject_id)
    person.is_active = person.is_app_admin = True
    denied = (
        replace(ctx, api_key_id=uuid4())
        if keyed
        else replace(ctx, subject_is_publisher_fallback=True)
    )
    result = await service.state(denied)
    assert not result.scopes[0].applicable and not result.scopes[1].applicable
    with pytest.raises(AuthorizationError):
        await service.update_scope(denied, "deployment", OnboardingScopeUpdate(completed=True))


@pytest.mark.security
@pytest.mark.parametrize("scope", ["deployment", "organization"])
@pytest.mark.parametrize("person_state", ["missing", "inactive"])
async def test_shared_write_requires_a_live_person(
    start: StartFixture, monkeypatch, scope, person_state
):
    ctx, _, _, service = start
    person = await user_repo.get_by_id(service.db, ctx.subject_id)
    person.is_active = False
    if person_state == "missing":
        monkeypatch.setattr(user_repo, "get_by_id", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError):
        await service.update_scope(ctx, scope, OnboardingScopeUpdate(completed=True))


@pytest.mark.parametrize(
    "scope,step", [("deployment", "member.tools"), ("organization", "admin.deployment")]
)
async def test_shared_progress_rejects_screens_from_another_scope(start: StartFixture, scope, step):
    ctx, _, _, service = start
    person = await user_repo.get_by_id(service.db, ctx.subject_id)
    person.is_active = person.is_app_admin = True
    with pytest.raises(BadRequestError):
        await service.update_scope(ctx, scope, OnboardingScopeUpdate(current_step=step))


@pytest.mark.parametrize(
    "scope,step", [("deployment", "admin.deployment"), ("organization", "admin.models")]
)
async def test_shared_completion_is_idempotent_and_does_not_complete_personal(
    start: StartFixture, monkeypatch, scope, step
):
    ctx, member, _, service = start
    person = await user_repo.get_by_id(service.db, ctx.subject_id)
    person.is_active = person.is_app_admin = True
    monkeypatch.setattr(
        onboarding_repo, "organization_for_update", organization_repo.get_by_id_for_update
    )
    deployment = DeploymentSettings()
    monkeypatch.setattr(
        onboarding_repo, "deployment_for_update", AsyncMock(return_value=deployment)
    )
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=deployment))
    visited = await service.update_scope(ctx, scope, OnboardingScopeUpdate(current_step=step))
    state = next(item for item in visited.scopes if item.scope == scope)
    assert state.current_step == step and not state.completed
    finished = await service.update_scope(ctx, scope, OnboardingScopeUpdate(completed=True))
    completed = next(item for item in finished.scopes if item.scope == scope)
    assert completed.completed and completed.current_step is None
    repeated = await service.update_scope(
        ctx, scope, OnboardingScopeUpdate(current_step=step, completed=True)
    )
    assert (
        next(item for item in repeated.scopes if item.scope == scope).completed_at
        == completed.completed_at
    )
    assert member.onboarding_completed_at is None


async def test_personal_scope_keeps_existing_completion_and_snooze_contract(start: StartFixture):
    ctx, member, _, service = start
    result = await service.update_scope(
        ctx, "personal", OnboardingScopeUpdate(current_step="member.tools")
    )
    assert result.current_step == "member.tools"
    assert member.onboarding_completed_at is None
    finished = await service.update_scope(ctx, "personal", OnboardingScopeUpdate(completed=True))
    assert finished.completed and finished.scopes[-1].completed
    assert not finished.scopes[1].completed


async def test_missing_organization_after_admission_is_controlled(start: StartFixture, monkeypatch):
    ctx, _, _, service = start
    person = await user_repo.get_by_id(service.db, ctx.subject_id)
    person.is_active = True
    monkeypatch.setattr(onboarding_repo, "organization_for_update", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await service.update_scope(ctx, "organization", OnboardingScopeUpdate(completed=True))


@pytest.mark.parametrize(
    "data",
    [
        {"completed": False},
        {"dismissed": True},
        {"scope": "deployment"},
        {"current_step": "unknown"},
    ],
)
def test_shared_update_has_no_reset_snooze_or_scope_override(data):
    with pytest.raises(ValidationError):
        OnboardingScopeUpdate.model_validate(data)


async def test_app_admin_can_start_before_any_organization(start: StartFixture, monkeypatch):
    _, _, db, service = start
    from app.db.models.user import User

    actor = User(is_app_admin=True, is_active=True)
    monkeypatch.setattr(onboarding_repo, "deployment_actor", AsyncMock(return_value=actor))
    empty = await service.deployment_state(actor)
    assert empty.organization_id is None and empty.organization_name is None
    assert [scope.applicable for scope in empty.scopes] == [True, False, False]
    assert empty.active_scope == "deployment"
    row = DeploymentSettings()
    monkeypatch.setattr(onboarding_repo, "deployment_for_update", AsyncMock(return_value=row))
    monkeypatch.setattr(deployment_settings_repo, "get", AsyncMock(return_value=row))
    visited = await service.update_deployment(
        actor, OnboardingScopeUpdate(current_step="admin.deployment")
    )
    assert visited.scopes[0].current_step == "admin.deployment"
    result = await service.update_deployment(actor, OnboardingScopeUpdate(completed=True))
    assert result.active_scope is None and result.scopes[0].completed
    assert db.commit.await_count == 0


@pytest.mark.security
@pytest.mark.parametrize("is_admin,is_active", [(False, True), (True, False)])
async def test_no_organization_path_keeps_live_app_admin_gate(
    start: StartFixture, is_admin, is_active
):
    from app.db.models.user import User

    _, _, _, service = start
    actor = User(is_app_admin=is_admin, is_active=is_active)
    with pytest.raises(AuthorizationError):
        await service.deployment_state(actor)
    with pytest.raises(AuthorizationError):
        await service.update_deployment(actor, OnboardingScopeUpdate(completed=True))


async def test_no_organization_path_rejects_personal_screen(start: StartFixture):
    from app.db.models.user import User

    _, _, _, service = start
    with pytest.raises(BadRequestError):
        await service.update_deployment(
            User(is_app_admin=True, is_active=True),
            OnboardingScopeUpdate(current_step="preferences.language"),
        )


@pytest.mark.security
@pytest.mark.parametrize("change", ["demoted", "inactive", "missing"])
async def test_shared_write_rechecks_authority_after_waiting_for_progress_lock(
    start, monkeypatch, change
):
    ctx, member, _, service = start
    person = await user_repo.get_by_id(service.db, member.user_id)
    person.is_active = True
    org = await organization_repo.get_by_id(service.db, ctx.organization_id)

    async def lock(_db, _org):
        if change == "demoted":
            member.role = "member"
        elif change == "inactive":
            person.is_active = False
        else:
            monkeypatch.setattr(onboarding_repo, "shared_identity", AsyncMock(return_value=None))
        return org

    monkeypatch.setattr(onboarding_repo, "organization_for_update", lock)
    with pytest.raises((AuthorizationError, NotFoundError)):
        await service.update_scope(ctx, "organization", OnboardingScopeUpdate(completed=True))
    assert org.onboarding_completed_at is None


@pytest.mark.security
@pytest.mark.parametrize("missing", [False, True])
async def test_no_organization_write_rechecks_app_admin_after_progress_lock(
    start, monkeypatch, missing
):
    from app.db.models.user import User

    _, _, _, service = start
    actor = User(is_active=True, is_app_admin=True)
    row = DeploymentSettings()

    async def lock(_db):
        actor.is_app_admin = False
        return row

    monkeypatch.setattr(onboarding_repo, "deployment_for_update", lock)
    monkeypatch.setattr(
        onboarding_repo, "deployment_actor", AsyncMock(return_value=None if missing else actor)
    )
    with pytest.raises(AuthorizationError):
        await service.update_deployment(actor, OnboardingScopeUpdate(completed=True))
    assert row.onboarding_completed_at is None


async def test_shared_step_noop_and_explicit_clear_preserve_completion_semantics(
    start, monkeypatch
):
    ctx, member, _, service = start
    person = await user_repo.get_by_id(service.db, member.user_id)
    person.is_active = True
    org = await organization_repo.get_by_id(service.db, ctx.organization_id)
    monkeypatch.setattr(onboarding_repo, "organization_for_update", AsyncMock(return_value=org))
    first = await service.update_scope(
        ctx, "organization", OnboardingScopeUpdate(current_step="admin.tools")
    )
    stamp = first.scopes[1].updated_at
    unchanged = await service.update_scope(
        ctx, "organization", OnboardingScopeUpdate(current_step="admin.tools")
    )
    assert unchanged.scopes[1].updated_at == stamp
    cleared = await service.update_scope(
        ctx, "organization", OnboardingScopeUpdate(current_step=None)
    )
    assert cleared.scopes[1].current_step is None and not cleared.scopes[1].completed
    assert cleared.scopes[1].updated_at is not None


@pytest.mark.parametrize("payload", [{}, {"completed": None}, {"current_step": None}])
async def test_personal_scope_adapter_preserves_omitted_and_explicit_null(
    start: StartFixture, payload: dict[str, None]
) -> None:
    ctx, member, _, service = start
    member.onboarding_goal = "meeting"
    member.onboarding_current_step = "member.tools"
    member.onboarding_dismissed_at = datetime.now(UTC)
    dismissed = member.onboarding_dismissed_at
    await service.update_scope(ctx, "personal", OnboardingScopeUpdate.model_validate(payload))
    assert member.onboarding_goal == "meeting"
    assert member.onboarding_dismissed_at == dismissed
    assert member.onboarding_completed_at is None
    assert member.onboarding_current_step == (None if "current_step" in payload else "member.tools")
