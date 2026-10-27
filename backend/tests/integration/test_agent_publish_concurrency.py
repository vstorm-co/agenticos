"""Drafts, versions and serving pointers change under one per-agent lock."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.schemas.agent_environment import EnvironmentUpdate
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService
from tests.integration._keys import provider_key

pytestmark = pytest.mark.anyio


async def _setup(db: AsyncSession, *, published: bool = False) -> tuple[AuthContext, Agent]:
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    organization = Organization(name="Acme", slug=f"acme-{uuid4()}", created_by_user_id=user.id)
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role="owner"))
    spec = AgentSpec(name="Support", instructions="Original instructions")
    agent = Agent(
        organization_id=organization.id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=spec.name,
        slug="support",
        visibility="org",
        draft_spec=spec.model_dump(mode="json"),
    )
    db.add(agent)
    await db.flush()
    if published:
        version = AgentVersion(
            organization_id=organization.id,
            agent_id=agent.id,
            version=1,
            spec=spec.model_dump(mode="json"),
        )
        db.add(version)
        await db.flush()
        agent.current_version_id, agent.status = version.id, "published"
        db.add(
            AgentEnvironment(
                organization_id=organization.id,
                agent_id=agent.id,
                name="production",
                version_id=version.id,
                is_default=True,
                tracks_latest=True,
            )
        )
    await db.commit()
    return AuthContext(user_id=user.id, organization_id=organization.id, role="owner"), agent


def _pause_validation(monkeypatch: pytest.MonkeyPatch) -> tuple[asyncio.Event, asyncio.Event]:
    entered, release = asyncio.Event(), asyncio.Event()

    async def validate(
        self: AgentRegistryService,
        ctx: AuthContext,
        spec: AgentSpec,
        *,
        agent_id: UUID | None = None,
    ) -> None:
        entered.set()
        await release.wait()

    monkeypatch.setattr(AgentRegistryService, "validate_spec", validate)
    return entered, release


@pytest.mark.parametrize("rollback", [False, True])
async def test_a_newer_draft_save_waits_and_survives_publication(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, rollback: bool
) -> None:
    ctx, agent = await _setup(db, published=rollback)
    source_id = agent.current_version_id
    entered, release = _pause_validation(monkeypatch)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def publish() -> UUID:
        async with factory() as session:
            service = AgentRegistryService(session)
            if rollback:
                assert source_id is not None
                version = await service.rollback(ctx, agent.id, to_version_id=source_id)
            else:
                version = await service.publish(ctx, agent.id)
            await session.commit()
            return version.id

    newer = AgentSpec(name="New support", instructions="Newer unsent edits")

    async def save() -> None:
        async with factory() as session:
            await AgentRegistryService(session).save_draft(ctx, agent.id, newer)
            await session.commit()

    async with asyncio.timeout(15), asyncio.TaskGroup() as group:
        publishing = group.create_task(publish())
        await entered.wait()
        saving = group.create_task(save())
        done, _ = await asyncio.wait({saving}, timeout=0.05)
        assert not done
        release.set()
    draft = await db.scalar(select(Agent.draft_spec).where(Agent.id == agent.id))
    frozen = await db.scalar(
        select(AgentVersion.spec).where(AgentVersion.id == publishing.result())
    )
    assert draft == newer.model_dump(mode="json")
    assert frozen is not None and frozen["instructions"] == "Original instructions"
    assert await db.scalar(select(Agent.name).where(Agent.id == agent.id)) == newer.name


@pytest.mark.parametrize("rollback", [False, True])
async def test_concurrent_publications_allocate_distinct_versions(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, rollback: bool
) -> None:
    ctx, agent = await _setup(db, published=rollback)
    source_id = agent.current_version_id
    entered, release = _pause_validation(monkeypatch)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def publish() -> int:
        async with factory() as session:
            service = AgentRegistryService(session)
            if rollback:
                assert source_id is not None
                version = await service.rollback(ctx, agent.id, to_version_id=source_id)
            else:
                version = await service.publish(ctx, agent.id)
            await session.commit()
            return version.version

    async with asyncio.timeout(15), asyncio.TaskGroup() as group:
        first = group.create_task(publish())
        await entered.wait()
        second = group.create_task(publish())
        done, _ = await asyncio.wait({second}, timeout=0.05)
        assert not done
        release.set()
    assert sorted([first.result(), second.result()]) == ([2, 3] if rollback else [1, 2])


async def test_a_new_run_is_not_blocked_by_the_publication_lock(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, agent = await _setup(db, published=True)
    entered, release = _pause_validation(monkeypatch)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def publish() -> None:
        async with factory() as session:
            await AgentRegistryService(session).publish(ctx, agent.id)
            await session.commit()

    async def admit_run() -> None:
        async with factory() as session:
            session.add(
                AgentRun(
                    organization_id=ctx.organization_id,
                    agent_id=agent.id,
                    agent_version_id=agent.current_version_id,
                    user_id=ctx.user_id,
                    surface="api",
                    status="running",
                )
            )
            await session.commit()

    async with asyncio.timeout(15), asyncio.TaskGroup() as group:
        group.create_task(publish())
        await entered.wait()
        # FOR UPDATE would block the foreign-key key-share lock here.
        await asyncio.wait_for(admit_run(), timeout=3)
        release.set()
    assert len(list(await db.scalars(select(AgentRun.id)))) == 1


async def test_a_waiting_promotion_reads_fresh_environment_state_and_keeps_pointers_aligned(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, agent = await _setup(db, published=True)
    old_version = agent.current_version_id
    assert old_version is not None
    environment_id = (await db.scalars(select(AgentEnvironment.id))).one()
    entered, release = _pause_validation(monkeypatch)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def publish() -> None:
        async with factory() as session:
            await AgentRegistryService(session).publish(ctx, agent.id)
            await session.commit()

    async def promote() -> None:
        async with factory() as session:
            # Keep an identity-map copy from before the publication commits.
            cached = await session.get(AgentEnvironment, environment_id)
            assert cached is not None and cached.version_id == old_version
            await AgentEnvironmentService(session).update(
                ctx,
                agent.id,
                environment_id,
                EnvironmentUpdate(version_id=old_version, tracks_latest=False),
            )
            await session.commit()

    async with asyncio.timeout(15), asyncio.TaskGroup() as group:
        group.create_task(publish())
        await entered.wait()
        promoting = group.create_task(promote())
        done, _ = await asyncio.wait({promoting}, timeout=0.05)
        assert not done
        release.set()
    assert (
        await db.scalar(select(Agent.current_version_id).where(Agent.id == agent.id)) == old_version
    )
    assert (
        await db.scalar(
            select(AgentEnvironment.version_id).where(AgentEnvironment.id == environment_id)
        )
        == old_version
    )
    assert (
        await db.scalar(
            select(AgentEnvironment.tracks_latest).where(AgentEnvironment.id == environment_id)
        )
        is False
    )


async def test_assistant_installation_does_not_republish_a_version_committed_while_it_waited(
    db: AsyncSession,
) -> None:
    from app.db.models.credential import ModelProfile
    from app.services.assistant import AssistantService

    ctx, agent = await _setup(db, published=True)
    db.add(
        ModelProfile(
            organization_id=ctx.organization_id,
            label="Available",
            provider="openai",
            model="gpt-4.1",
            secret_id=await provider_key(db, ctx.organization_id),
        )
    )
    await db.flush()
    stale = Agent(
        id=agent.id,
        organization_id=ctx.organization_id,
        name="Support",
        slug="support",
        draft_spec=agent.draft_spec,
    )
    result = await AssistantService(db)._publish_when_possible(ctx.organization_id, stale)
    assert result.current_version_id == agent.current_version_id
    assert len(list(await db.scalars(select(AgentVersion.id)))) == 1
