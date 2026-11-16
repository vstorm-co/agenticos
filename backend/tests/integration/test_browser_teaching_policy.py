"""Policy and personal choices retain exact-generation authority under revocation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.browser_teaching import TeachingReason, TeachingRefused
from app.core.config import settings
from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.audit_log import AppAdminAuditLog
from app.repositories import browser_teaching as repo
from app.schemas.browser_teaching import TeachingPolicyWrite, TeachingPreferenceWrite
from app.services.browser_teaching import _access, _policy
from tests.integration.test_browser_teaching import teaching as teaching
from tests.integration.test_browser_teaching_refinement import opt_in

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_absent_policy_defaults_off_and_cas_updates_are_audited_once(teaching):
    t = teaching
    await t.db.delete(await repo.policy(t.db, t.org.id))
    await t.db.flush()
    service = _policy.BrowserTeachingPolicyService(t.db)
    absent = await service.get(t.ctx)
    assert not absent.enabled and absent.generation is None and absent.deployment_enabled
    created = await service.update(t.ctx, TeachingPolicyWrite(generation=None, enabled=False))
    assert not created.enabled and created.generation is not None
    same = await service.update(
        t.ctx, TeachingPolicyWrite(generation=created.generation, enabled=False)
    )
    assert same == created
    changed = await service.update(
        t.ctx, TeachingPolicyWrite(generation=created.generation, enabled=True)
    )
    assert changed.enabled and changed.generation != created.generation
    with pytest.raises(ConflictError):
        await service.update(
            t.ctx, TeachingPolicyWrite(generation=created.generation, enabled=False)
        )
    assert await service.get(t.ctx) == changed
    assert (
        await t.db.scalar(
            select(func.count(AppAdminAuditLog.id)).where(
                AppAdminAuditLog.action == "browser_teaching.policy_changed",
                AppAdminAuditLog.organization_id == t.org.id,
            )
        )
        == 2
    )


@pytest.mark.parametrize("after_lock", [False, True])
async def test_org_settings_permission_is_checked_again_after_waiting_for_the_policy_lock(
    teaching, monkeypatch, after_lock
):
    t = teaching
    denied = AuthContext(user_id=t.owner.id, organization_id=t.org.id, role="member")
    assert not denied.has(Perm.ORG_SETTINGS)
    calls = [t.ctx, denied] if after_lock else [denied]
    monkeypatch.setattr(_access, "person", AsyncMock(side_effect=calls))
    current = await repo.policy(t.db, t.org.id)
    generation = current.generation
    with pytest.raises(AuthorizationError):
        await _policy.BrowserTeachingPolicyService(t.db).update(
            t.ctx,
            TeachingPolicyWrite(generation=generation, enabled=False),
        )
    assert current.enabled and current.generation == generation


async def test_personal_choice_defaults_off_and_uses_generation_cas_without_duplicate_audits(
    teaching,
):
    t = teaching
    service = _policy.BrowserTeachingPolicyService(t.db)
    absent = await service.preference(t.ctx, t.agent.id)
    assert not absent.enabled and absent.allowed and absent.generation is None
    created = await service.update_preference(
        t.ctx, t.agent.id, TeachingPreferenceWrite(generation=None, enabled=False)
    )
    assert not created.enabled and created.generation is not None
    same = await service.update_preference(
        t.ctx, t.agent.id, TeachingPreferenceWrite(generation=created.generation, enabled=False)
    )
    assert same == created
    enabled = await service.update_preference(
        t.ctx, t.agent.id, TeachingPreferenceWrite(generation=created.generation, enabled=True)
    )
    assert enabled.enabled and enabled.generation != created.generation
    with pytest.raises(ConflictError):
        await service.update_preference(
            t.ctx, t.agent.id, TeachingPreferenceWrite(generation=created.generation, enabled=False)
        )
    disabled = await service.update_preference(
        t.ctx, t.agent.id, TeachingPreferenceWrite(generation=enabled.generation, enabled=False)
    )
    assert not disabled.enabled and disabled.generation != enabled.generation
    assert (
        await t.db.scalar(
            select(func.count(AppAdminAuditLog.id)).where(
                AppAdminAuditLog.action == "browser_teaching.preference_changed",
                AppAdminAuditLog.organization_id == t.org.id,
            )
        )
        == 3
    )


@pytest.mark.parametrize(
    "condition",
    [
        "missing",
        "archived",
        "grant",
        "unpublished",
        "missing_version",
        "wrong_agent",
        "malformed",
        "capture_disabled",
        "learning_disabled",
    ],
)
async def test_new_opt_in_requires_current_published_capability_and_agent_access(
    teaching, monkeypatch, condition
):
    t = teaching
    service = _policy.BrowserTeachingPolicyService(t.db)
    inaccessible = condition in {"missing", "archived", "grant"}
    if condition == "missing":
        monkeypatch.setattr(_policy.agent_repo, "get", AsyncMock(return_value=None))
    elif condition == "archived":
        t.agent.status = "archived"
    elif condition == "grant":
        monkeypatch.setattr(_policy, "resolve_access", AsyncMock(return_value=False))
    elif condition == "unpublished":
        t.agent.current_version_id = None
    elif condition in {"missing_version", "wrong_agent", "malformed"}:
        version = (
            None
            if condition == "missing_version"
            else SimpleNamespace(
                agent_id=uuid4() if condition == "wrong_agent" else t.agent.id,
                spec={} if condition == "malformed" else t.version.spec,
            )
        )
        monkeypatch.setattr(_policy.agent_repo, "get_version", AsyncMock(return_value=version))
    else:
        binding = t.version.spec["capabilities"][0]
        field = "allow_teaching" if condition == "capture_disabled" else "learn_site_procedures"
        t.version.spec = {
            **t.version.spec,
            "capabilities": [{**binding, "config": {**binding["config"], field: False}}],
        }
    await t.db.flush()
    if inaccessible:
        with pytest.raises(NotFoundError):
            await service.preference(t.ctx, t.agent.id)
        with pytest.raises(NotFoundError):
            await service.update_preference(
                t.ctx, t.agent.id, TeachingPreferenceWrite(generation=None, enabled=True)
            )
    else:
        assert not (await service.preference(t.ctx, t.agent.id)).allowed
        with pytest.raises(TeachingRefused) as caught:
            await service.update_preference(
                t.ctx, t.agent.id, TeachingPreferenceWrite(generation=None, enabled=True)
            )
        assert caught.value.reason == TeachingReason.UNAVAILABLE
    assert await repo.preference(t.db, t.org.id, t.owner.id, t.agent.id) is None


async def test_recorded_opt_in_can_be_revoked_after_agent_access_is_removed(teaching, monkeypatch):
    t = teaching
    pref = await opt_in(t)
    generation = pref.generation
    monkeypatch.setattr(_policy, "resolve_access", AsyncMock(return_value=False))
    service = _policy.BrowserTeachingPolicyService(t.db)
    current = await service.preference(t.ctx, t.agent.id)
    assert current.enabled and not current.allowed and current.generation == generation
    with pytest.raises(NotFoundError):
        await service.update_preference(
            t.ctx, t.agent.id, TeachingPreferenceWrite(generation=generation, enabled=True)
        )
    revoked = await service.update_preference(
        t.ctx, t.agent.id, TeachingPreferenceWrite(generation=generation, enabled=False)
    )
    assert not revoked.enabled and not revoked.allowed and revoked.generation != generation


@pytest.mark.parametrize("gate", ["deployment", "organization", "policy"])
async def test_disabled_admission_never_accepts_a_new_member_opt_in(teaching, monkeypatch, gate):
    t = teaching
    if gate == "deployment":
        monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", False)
    elif gate == "organization":
        monkeypatch.setattr(settings, "BROWSER_TEACHING_ORGANIZATION_IDS", [])
    else:
        (await repo.policy(t.db, t.org.id)).enabled = False
        await t.db.flush()
    service = _policy.BrowserTeachingPolicyService(t.db)
    assert not (await service.preference(t.ctx, t.agent.id)).allowed
    with pytest.raises(TeachingRefused) as caught:
        await service.update_preference(
            t.ctx, t.agent.id, TeachingPreferenceWrite(generation=None, enabled=True)
        )
    assert caught.value.reason == TeachingReason.DISABLED
