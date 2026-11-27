"""Real constraints and physical GUI fencing across private views."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.conversation_environment import ConversationEnvironment
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_environment as environments

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def identities(db: AsyncSession) -> tuple[User, Organization, Conversation, Agent]:
    user = User(id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(id=uuid4(), name="Private GUI", slug=uuid4().hex, created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    conversation = Conversation(id=uuid4(), user_id=user.id, organization_id=org.id)
    agent = Agent(
        id=uuid4(), organization_id=org.id, name="Browser", slug=uuid4().hex, owner_user_id=user.id
    )
    db.add_all([conversation, agent])
    await db.flush()
    return user, org, conversation, agent


def environment(
    user: User, org: Organization, conversation: Conversation, agent: Agent
) -> ConversationEnvironment:
    return ConversationEnvironment(
        id=uuid4(),
        organization_id=org.id,
        vault_organization_id=org.id,
        user_id=user.id,
        conversation_id=conversation.id,
        agent_id=agent.id,
        kind="browser",
        execution_target="agent",
        session_lifetime="conversation",
        idle_seconds=900,
        state="starting",
        fingerprint="a" * 64,
        revision=1,
        provisioning_attempt=0,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


async def test_only_one_active_owner_environment_and_expiry_releases_slot(db: AsyncSession):
    user, org, conversation, agent = await identities(db)
    first = environment(user, org, conversation, agent)
    db.add(first)
    await db.flush()
    async with db.begin_nested() as transaction:
        with pytest.raises(IntegrityError):
            db.add(environment(user, org, conversation, agent))
            await db.flush()
        await transaction.rollback()
    first.state = "expired"
    await db.flush()
    db.add(environment(user, org, conversation, agent))
    await db.flush()
    assert await environments.active_count(db, org.id, user.id, datetime.now(UTC)) == 1


async def test_physical_driver_is_exclusive_across_organizations_and_fenced_after_expiry(
    db: AsyncSession,
):
    first, first_org, _, _ = await identities(db)
    second, second_org, _, _ = await identities(db)
    now = datetime.now(UTC)
    a, b = uuid4(), uuid4()
    assert await environments.claim_driver(
        db,
        "same-physical-desktop",
        organization_id=first_org.id,
        user_id=first.id,
        token=a,
        control="agent",
        now=now,
        lease_until=now + timedelta(seconds=120),
    )
    assert not await environments.claim_driver(
        db,
        "same-physical-desktop",
        organization_id=second_org.id,
        user_id=second.id,
        token=b,
        control="human",
        now=now,
        lease_until=now + timedelta(seconds=120),
    )
    later = now + timedelta(seconds=121)
    assert await environments.claim_driver(
        db,
        "same-physical-desktop",
        organization_id=second_org.id,
        user_id=second.id,
        token=b,
        control="human",
        now=later,
        lease_until=later + timedelta(seconds=120),
    )
    assert not await environments.renew_driver(
        db, "same-physical-desktop", token=a, now=later, lease_until=later + timedelta(minutes=5)
    )
    await environments.release_driver(db, "same-physical-desktop", token=a)
    held = await environments.driver(db, "same-physical-desktop")
    assert held is not None and held.lease_token == b
    await environments.release_driver(db, "same-physical-desktop", token=b)
    assert await environments.driver(db, "same-physical-desktop") is None


async def test_conversation_delete_preserves_original_vault_scope_and_cleanup_journal(
    db: AsyncSession,
):
    user, org, conversation, agent = await identities(db)
    row = environment(user, org, conversation, agent)
    row.resource_ciphertext, row.resource_key_version = "sealed-private-handle", 1
    db.add(row)
    await db.flush()
    identity, org_id, conversation_id = row.id, org.id, conversation.id
    await db.execute(delete(Conversation).where(Conversation.id == conversation_id))
    await db.flush()
    db.expire_all()
    saved = await db.scalar(
        select(ConversationEnvironment).where(ConversationEnvironment.id == identity)
    )
    assert saved is not None
    assert saved.organization_id is None and saved.conversation_id is None
    assert saved.vault_organization_id == org_id
    assert saved.resource_ciphertext == "sealed-private-handle"
    due = await environments.sweep_candidates(db, datetime.now(UTC))
    assert [item.id for item in due] == [identity]


async def test_failed_or_ended_known_provider_still_uses_quota_until_cleanup(db: AsyncSession):
    user, org, conversation, agent = await identities(db)
    row = environment(user, org, conversation, agent)
    row.state = "failed"
    row.resource_ciphertext, row.resource_key_version = "sealed-private-handle", 1
    row.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db.add(row)
    await db.flush()
    assert await environments.active_count(db, org.id, user.id, datetime.now(UTC)) == 1
    row.state = "expired"
    await db.flush()
    assert await environments.active_count(db, org.id, user.id, datetime.now(UTC)) == 1
    row.resource_ciphertext, row.resource_key_version = None, None
    await db.flush()
    assert await environments.active_count(db, org.id, user.id, datetime.now(UTC)) == 0


@pytest.mark.parametrize("lifetime", ["run", "conversation"])
async def test_instruction_only_republish_reuses_live_target_with_fresh_run_authority(
    db: AsyncSession, monkeypatch, lifetime
):
    """Creation provenance stays V1 while a legitimate V2 run adopts unchanged DOM."""
    from sqlalchemy import func

    from app.agents.capabilities.browser_use._page import BrowserTarget
    from app.agents.spec import AgentSpec, CapabilityBindingSpec
    from app.core.config import settings
    from app.core.permissions import AuthContext
    from app.db.models.agent import AgentVersion
    from app.db.models.agent_run import AgentRun
    from app.db.models.organization import OrganizationMember
    from app.schemas.conversation_environment import ConversationEnvironmentStart
    from app.services.conversation_environment_agent import AgentEnvironment
    from app.services.conversation_environment_policy import (
        EnvironmentNotReady,
        authority,
        settings_for,
    )
    from app.services.conversation_environment_resources import BrowserEnvironmentResource
    from app.services.conversation_environments import ConversationEnvironmentService

    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "http://browser:9222")
    user, org, conversation, agent = await identities(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    spec = AgentSpec(
        name="Browser",
        instructions="First instructions",
        capabilities=[
            CapabilityBindingSpec(id="browser_use", config={"session_lifetime": lifetime})
        ],
    )
    v1 = AgentVersion(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec=spec.model_dump(mode="json"),
        published_by_user_id=user.id,
    )
    db.add(v1)
    await db.flush()
    agent.current_version_id = v1.id
    await db.flush()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    admitted = await authority(db, ctx, conversation_id=conversation.id, agent_id=agent.id)
    configured = await settings_for(db, admitted, "browser")
    row = environment(user, org, conversation, agent)
    row.session_lifetime = lifetime
    row.agent_version_id, row.fingerprint, row.provisioning_attempt = (
        v1.id,
        configured.fingerprint,
        1,
    )
    db.add(row)
    await db.flush()
    service = ConversationEnvironmentService(db)
    target = BrowserEnvironmentResource(
        environment_id=row.id,
        organization_id=org.id,
        cdp_url="http://browser:9222",
        tabs={"main": BrowserTarget(context_id="same-context", target_id="same-live-target")},
    )
    payload = service.payload(row)
    assert await service.store_resource(payload, 1, target, "physical")
    assert await service.ready(payload, 1)
    v2 = AgentVersion(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=2,
        spec=spec.model_copy(update={"instructions": "Updated instructions"}).model_dump(
            mode="json"
        ),
        published_by_user_id=user.id,
    )
    db.add(v2)
    await db.flush()
    agent.current_version_id = v2.id
    run = AgentRun(
        id=uuid4(),
        organization_id=org.id,
        user_id=user.id,
        agent_id=agent.id,
        agent_version_id=v2.id,
        conversation_id=conversation.id,
        surface="web",
        status="running",
    )
    db.add(run)
    await db.flush()
    count_before = await db.scalar(select(func.count()).select_from(AgentRun))
    read = await service.read(ctx, conversation.id, agent.id, "browser")
    ensured = await service.ensure(
        ctx, conversation.id, "browser", ConversationEnvironmentStart(agent_id=agent.id)
    )
    assert read.id == ensured.id == row.id and read.state == ensured.state == "ready"
    assert await db.scalar(select(func.count()).select_from(AgentRun)) == count_before
    adapter = AgentEnvironment(
        ctx,
        conversation_id=conversation.id,
        agent_id=agent.id,
        version_id=v2.id,
        run_id=run.id,
        target="agent",
        kind="browser",
    )
    adapter.environment_id = row.id
    actual, current, retained = await adapter.live(db)
    await adapter._check(db)
    assert actual.agent_version_id == v1.id
    assert current.authority.version_id == v2.id
    assert retained == target
    old = AgentEnvironment(
        ctx,
        conversation_id=conversation.id,
        agent_id=agent.id,
        version_id=v1.id,
        run_id=run.id,
        target="agent",
        kind="browser",
    )
    old.environment_id = row.id
    with pytest.raises(EnvironmentNotReady):
        await old.live(db)

    # Driver admission and producer adoption share the real database transaction.
    # An unrelated/busy driver must not bind this manually prepared target.
    from contextlib import asynccontextmanager

    from app.core.exceptions import ConflictError
    from app.services import conversation_environment_driver as drivers

    @asynccontextmanager
    async def session():
        async with db.begin_nested():
            yield db

    monkeypatch.setattr(drivers, "get_db_context", session)
    held_token = uuid4()
    now = datetime.now(UTC)
    assert await environments.claim_driver(
        db,
        "physical",
        organization_id=org.id,
        user_id=user.id,
        token=held_token,
        control="human",
        now=now,
        lease_until=now + timedelta(seconds=120),
    )
    driver = drivers.EnvironmentDriver(
        "physical", ctx, "agent", adapter._check, on_acquired=adapter._adopt
    )
    with pytest.raises(ConflictError):
        await driver.acquire()
    assert row.source_run_id is None
    await environments.release_driver(db, "physical", token=held_token)

    # If adoption itself fails, neither the new physical lease nor the producer
    # pointer may escape the transaction.
    async def fail_adoption(actual):
        await adapter._adopt(actual)
        raise ConflictError(message="Adoption transaction refused")

    failing = drivers.EnvironmentDriver(
        "physical", ctx, "agent", adapter._check, on_acquired=fail_adoption
    )
    with pytest.raises(ConflictError, match="Adoption transaction refused"):
        await failing.acquire()
    assert await environments.driver(db, "physical") is None
    await db.refresh(row)
    assert row.source_run_id is None
    await driver.acquire()
    try:
        assert row.source_run_id == (run.id if lifetime == "run" else None)
        assert row.agent_version_id == v1.id
    finally:
        await driver.close()
    run.status = "completed"
    await db.flush()
    candidates = await environments.sweep_candidates(db, datetime.now(UTC))
    assert (row.id in {candidate.id for candidate in candidates}) == (lifetime == "run")
