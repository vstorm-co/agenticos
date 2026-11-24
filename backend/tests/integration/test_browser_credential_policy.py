"""Shared browser authority is an owner-approved named policy, never generic sharing."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.browser_fill import BrowserFillRefused
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.secret_kinds import ApiKeySecret, BrowserLoginSecret, unseal_kind
from app.core.vault import VaultScope
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import OrganizationMember
from app.repositories import browser_credential as repo
from app.schemas.browser_credential import BrowserCredentialPolicyWrite
from app.services.browser_credentials import BrowserCredentialPolicyService, _access
from app.services.browser_credentials._bindings import BINDING_REFUSAL, binding_problem
from app.services.organization_secret import OrganizationSecretService
from tests.integration.test_browser_credential_plans import BrowserFixture
from tests.integration.test_browser_credential_plans import browser as browser
from tests.integration.test_personal_coding_accounts import context, organization, person
from tests.test_browser_credentials import PASSWORD, SEED, USERNAME, login

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def recipient(b: BrowserFixture):
    other = await person(b.db)
    b.db.add(OrganizationMember(organization_id=b.org.id, user_id=other.id, role="owner"))
    await b.db.flush()
    return other


async def test_explicit_shared_scope_rewraps_rotates_and_grants_only_the_named_agent_and_person(
    browser: BrowserFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b = browser
    other = await recipient(b)
    service = BrowserCredentialPolicyService(b.db)
    original = await service.get(b.ctx, b.secret.id)
    assert original.mode == "personal" and original.agent_ids == original.member_ids == []
    identical = BrowserCredentialPolicyWrite(
        generation=original.authorization_generation, mode="personal"
    )
    assert await service.update(b.ctx, b.secret.id, identical) == original
    assert not await repo.policy_exists(b.db, b.org.id, b.secret.id)
    request = BrowserCredentialPolicyWrite(
        generation=original.authorization_generation,
        mode="shared",
        agent_ids=(b.agent.id,),
        member_ids=(other.id,),
    )
    shared = await service.update(b.ctx, b.secret.id, request)
    assert (
        shared.mode == "shared"
        and shared.authorization_generation != original.authorization_generation
    )
    assert b.secret.usage_scope == "organization" and b.secret.owner_user_id == b.owner.id
    assert (
        unseal_kind(
            b.secret.sealed_secret,
            model=BrowserLoginSecret,
            scope=VaultScope.organization(b.org.id),
        )
        == login()
    )
    with pytest.raises(BadRequestError):
        unseal_kind(
            b.secret.sealed_secret,
            model=BrowserLoginSecret,
            scope=VaultScope.browser_member(b.org.id, b.owner.id),
        )
    granted = await _access.credential(
        b.db, context(other, b.org), secret_id=b.secret.id, agent_id=b.agent.id
    )
    assert granted.id == b.secret.id
    assert await repo.granted(b.db, b.org.id, b.secret.id, b.agent.id, other.id)
    assert not await repo.granted(b.db, uuid4(), b.secret.id, b.agent.id, other.id)
    for ctx, agent_id in ((b.ctx, b.agent.id), (context(other, b.org), uuid4())):
        with pytest.raises(BrowserFillRefused):
            await _access.credential(b.db, ctx, secret_id=b.secret.id, agent_id=agent_id)
    assert await OrganizationSecretService(b.db).list_secrets(context(other, b.org)) == []
    assert (await OrganizationSecretService(b.db).list_secrets(b.ctx))[0].id == b.secret.id
    assert (
        await OrganizationSecretService(b.db).resolve_for_bindings(
            context(other, b.org), [b.secret.id]
        )
        == {}
    )
    with pytest.raises(NotFoundError):
        await service.get(context(other, b.org), b.secret.id)
    count = len(list(await b.db.scalars(select(AppAdminAuditLog))))
    unchanged = await service.update(
        b.ctx,
        b.secret.id,
        request.model_copy(update={"generation": shared.authorization_generation}),
    )
    assert unchanged == shared
    assert len(list(await b.db.scalars(select(AppAdminAuditLog)))) == count
    with pytest.raises(BrowserFillRefused):
        await service.update(b.ctx, b.secret.id, request)

    # Ordinary value replacement keeps the owner and explicit policy, and seals
    # in the shared scope under the same row lock used by the native effect.
    await OrganizationSecretService(b.db).update(b.ctx, b.secret.id, value=login(totp=False))
    assert b.secret.authorization_generation != shared.authorization_generation
    assert await repo.granted(b.db, b.org.id, b.secret.id, b.agent.id, other.id)
    assert _access.open_value(b.secret) == login(totp=False)

    # Disabling deployment admission must not trap an owner in a shared policy.
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_FILL_ENABLED", False)
    monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_SHARED_ENABLED", False)
    personal = await service.update(
        b.ctx,
        b.secret.id,
        BrowserCredentialPolicyWrite(
            generation=b.secret.authorization_generation,
            mode="personal",
        ),
    )
    assert personal.mode == "personal" and personal.agent_ids == personal.member_ids == []
    assert not await repo.policy_exists(b.db, b.org.id, b.secret.id)
    assert not await repo.granted(b.db, b.org.id, b.secret.id, b.agent.id, other.id)
    assert unseal_kind(
        b.secret.sealed_secret,
        model=BrowserLoginSecret,
        scope=VaultScope.browser_member(b.org.id, b.owner.id),
    ) == login(totp=False)
    logs = json.dumps(list(await b.db.scalars(select(AppAdminAuditLog.details))), default=str)
    assert not any(value in logs for value in (PASSWORD, USERNAME, SEED))


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_agent",
        "foreign_agent",
        "archived_agent",
        "missing_member",
        "inactive_member",
        "disabled_shared",
        "disabled_fill",
    ],
)
async def test_policy_refusals_leave_ciphertext_generation_and_grants_unchanged(
    browser: BrowserFixture,
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    b = browser
    other = await recipient(b)
    agent_id, member_id = b.agent.id, other.id
    if invalid == "missing_agent":
        agent_id = uuid4()
    elif invalid == "foreign_agent":
        elsewhere = await organization(b.db, b.owner)
        # The lookup refuses an existing cross-tenant agent as well as an unknown ID.
        from app.db.models.agent import Agent

        foreign = Agent(
            organization_id=elsewhere.id,
            owner_user_id=b.owner.id,
            name="Elsewhere",
            slug=uuid4().hex,
        )
        b.db.add(foreign)
        await b.db.flush()
        agent_id = foreign.id
    elif invalid == "archived_agent":
        b.agent.status = "archived"
    elif invalid == "missing_member":
        member_id = uuid4()
    elif invalid == "inactive_member":
        other.is_active = False
    elif invalid == "disabled_shared":
        monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_SHARED_ENABLED", False)
    else:
        monkeypatch.setattr(settings, "BROWSER_CREDENTIAL_FILL_ENABLED", False)
    await b.db.flush()
    previous = b.secret.sealed_secret, b.secret.authorization_generation
    with pytest.raises(BrowserFillRefused):
        await BrowserCredentialPolicyService(b.db).update(
            b.ctx,
            b.secret.id,
            BrowserCredentialPolicyWrite(
                generation=b.secret.authorization_generation,
                mode="shared",
                agent_ids=(agent_id,),
                member_ids=(member_id,),
            ),
        )
    assert (b.secret.sealed_secret, b.secret.authorization_generation) == previous
    assert await repo.grants(b.db, b.org.id, b.secret.id) == ([], [])
    assert not await repo.policy_exists(b.db, b.org.id, b.secret.id)


async def test_shared_use_stops_when_owner_or_granted_member_leaves(
    browser: BrowserFixture,
) -> None:
    b = browser
    other = await recipient(b)
    await BrowserCredentialPolicyService(b.db).update(
        b.ctx,
        b.secret.id,
        BrowserCredentialPolicyWrite(
            generation=b.secret.authorization_generation,
            mode="shared",
            agent_ids=(b.agent.id,),
            member_ids=(other.id,),
        ),
    )
    other_ctx = context(other, b.org)
    assert await _access.credential(b.db, other_ctx, secret_id=b.secret.id, agent_id=b.agent.id)
    owner_membership = await b.db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == b.org.id,
            OrganizationMember.user_id == b.owner.id,
        )
    )
    await b.db.delete(owner_membership)
    await b.db.flush()
    with pytest.raises(BrowserFillRefused):
        await _access.credential(b.db, other_ctx, secret_id=b.secret.id, agent_id=b.agent.id)
    with pytest.raises(BrowserFillRefused):
        await BrowserCredentialPolicyService(b.db).get(b.ctx, b.secret.id)
    membership = await b.db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == b.org.id,
            OrganizationMember.user_id == other.id,
        )
    )
    await b.db.delete(membership)
    await b.db.flush()
    assert not await repo.granted(b.db, b.org.id, b.secret.id, b.agent.id, other.id)


async def test_binding_validation_never_lends_personal_or_generic_secret_authority(
    browser: BrowserFixture,
) -> None:
    b = browser
    assert await binding_problem(b.db, b.ctx, [], agent_id=None, provisioned=False) is None
    assert (
        await binding_problem(b.db, b.ctx, [b.secret.id], agent_id=b.agent.id, provisioned=True)
        is None
    )
    for agent_id, provisioned in ((None, True), (b.agent.id, False)):
        assert (
            await binding_problem(
                b.db, b.ctx, [b.secret.id], agent_id=agent_id, provisioned=provisioned
            )
            == BINDING_REFUSAL
        )
    other = await recipient(b)
    assert (
        await binding_problem(
            b.db, context(other, b.org), [b.secret.id], agent_id=b.agent.id, provisioned=True
        )
        == BINDING_REFUSAL
    )
    assert (
        await binding_problem(b.db, b.ctx, [uuid4()], agent_id=b.agent.id, provisioned=True)
        == BINDING_REFUSAL
    )
    technical = await OrganizationSecretService(b.db).create(
        b.ctx, name="Technical", value=ApiKeySecret(api_key="synthetic-key")
    )
    assert (
        await binding_problem(b.db, b.ctx, [technical.id], agent_id=b.agent.id, provisioned=True)
        == BINDING_REFUSAL
    )
    with pytest.raises(BrowserFillRefused):
        _access.open_value(technical)
    with pytest.raises(NotFoundError):
        await BrowserCredentialPolicyService(b.db).get(b.ctx, technical.id)
    assert await repo.policy_ids(b.db, b.org.id, []) == set()
    assert await repo.policy_ids(b.db, b.org.id, [b.secret.id]) == set()
