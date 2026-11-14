"""Promotion admission, pins and dataset deletion share a consistent transaction boundary."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import discard_deferred
from app.core.exceptions import BadRequestError, EvalSuiteInUseError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.dataset import Dataset
from app.repositories import agent_environment_repo, agent_repo, promotion_gate_repo
from app.schemas.agent_environment import EnvironmentUpdate
from app.schemas.dataset import DatasetCaseCreate
from app.schemas.promotion_gate import PromotionGateRead, PromotionGuardRead
from app.services.agent_environment import AgentEnvironmentService
from app.services.dataset import DatasetService
from app.services.eval_suite import EvalSuiteService
from app.services.promotion_gate import PromotionGateService
from tests.integration.test_promotion_gate import _agent, _dataset, _guarded, _owner

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _session(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessions() as db:
        try:
            yield db
        finally:
            # These tests assert database state, not deferred console broadcasts.
            discard_deferred(db)


@dataclass(frozen=True)
class World:
    ctx: AuthContext
    agent: UUID
    environment: UUID
    dataset: UUID
    suite: UUID
    second: UUID
    third: UUID


async def _prepared(sessions: async_sessionmaker[AsyncSession]) -> World:
    async with _session(sessions) as db:
        ctx = await _owner(db)
        agent, first = await _agent(db, ctx)
        dataset = await _dataset(db, ctx)
        environment, suite = await _guarded(db, ctx, agent, first, dataset, tracks_latest=True)
        second = AgentVersion(
            agent_id=agent.id, organization_id=ctx.organization_id, version=2, spec=first.spec
        )
        third = AgentVersion(
            agent_id=agent.id, organization_id=ctx.organization_id, version=3, spec=first.spec
        )
        db.add_all([second, third])
        await db.flush()
        world = World(ctx, agent.id, environment, dataset.id, suite.id, second.id, third.id)
        await db.commit()
        return world


def _passing(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    async def check(
        self: PromotionGateService,
        ctx: AuthContext | None,
        *,
        agent: Agent,
        environment: AgentEnvironment,
        version: AgentVersion,
    ) -> PromotionGateRead:
        return PromotionGateRead(
            environment_id=environment.id,
            environment_name=environment.name,
            version_id=version.id,
            version=version.version,
            guarded=True,
            passing=True,
            can_override=ctx is not None,
            guards=[PromotionGuardRead(suite_id=world.suite, suite_name="Guard", state="passed")],
        )

    monkeypatch.setattr(PromotionGateService, "check", check)


@pytest.mark.parametrize("change", ["newer", "pinned", "deleted"])
async def test_stale_automatic_follow_cannot_replace_a_newer_or_pinned_environment(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    change: Literal["newer", "pinned", "deleted"],
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    world = await _prepared(sessions)
    _passing(monkeypatch, world)
    async with _session(sessions) as one, _session(sessions) as two:
        agent = await agent_repo.get(one, world.agent, organization_id=world.ctx.organization_id)
        environment = await agent_environment_repo.get(
            one, world.environment, organization_id=world.ctx.organization_id
        )
        candidate = await agent_repo.get_version(
            one, world.second, organization_id=world.ctx.organization_id
        )
        assert agent is not None and environment is not None and candidate is not None
        other = AgentEnvironmentService(two)
        if change == "newer":
            await other.update(
                world.ctx, world.agent, world.environment, EnvironmentUpdate(version_id=world.third)
            )
        elif change == "pinned":
            await other.update(
                world.ctx, world.agent, world.environment, EnvironmentUpdate(tracks_latest=False)
            )
        else:
            await other.delete(world.ctx, world.agent, world.environment)
        await two.commit()
        assert await PromotionGateService(one)._advance(agent, environment, candidate) is False
        await one.commit()
        held = await agent_environment_repo.get(
            one, world.environment, organization_id=world.ctx.organization_id
        )
        if change == "deleted":
            assert held is None
        elif change == "newer":
            assert held is not None and held.version_id == world.third
        else:
            assert held is not None and not held.tracks_latest


async def test_pin_change_waits_for_a_promotion_that_is_checking_its_gate(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    world = await _prepared(sessions)
    async with _session(sessions) as setup:
        await DatasetService(setup).add_case(
            world.ctx,
            world.dataset,
            DatasetCaseCreate(input="Another question", reference_answer="Yes"),
        )
        await setup.commit()
    checked, release = asyncio.Event(), asyncio.Event()
    processes: asyncio.Queue[int] = asyncio.Queue()

    async def pause_gate(
        self: PromotionGateService,
        ctx: AuthContext,
        *,
        agent: Agent,
        environment: AgentEnvironment,
        version: AgentVersion,
        replaced_version_id: UUID,
        override_reason: str | None,
    ) -> None:
        checked.set()
        await release.wait()

    monkeypatch.setattr(PromotionGateService, "enforce", pause_gate)

    async def promote() -> None:
        async with _session(sessions) as db:
            await AgentEnvironmentService(db).update(
                world.ctx,
                world.agent,
                world.environment,
                EnvironmentUpdate(version_id=world.second),
            )
            await db.commit()

    async def repin() -> None:
        async with _session(sessions) as db:
            process = await db.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(process, int)
            await processes.put(process)
            await EvalSuiteService(db).move_pin(world.ctx, world.agent, world.suite)
            await db.commit()

    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        group.create_task(promote())
        await checked.wait()
        pin = group.create_task(repin())
        process = await processes.get()
        async with _session(sessions) as observer:
            while True:
                blocked = await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid) <> '{}'::int[]"), {"pid": process}
                )
                if blocked or pin.done():
                    break
                await asyncio.sleep(0.01)
        pin_committed_before_promotion = pin.done()
        release.set()
    assert not pin_committed_before_promotion


async def test_dataset_deletion_and_guard_attachment_cannot_both_succeed(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    world = await _prepared(sessions)
    async with _session(sessions) as db:
        await AgentEnvironmentService(db).update(
            world.ctx, world.agent, world.environment, EnvironmentUpdate(guard_suite_ids=[])
        )
        await db.commit()
    checked, release = asyncio.Event(), asyncio.Event()
    processes: asyncio.Queue[int] = asyncio.Queue()
    original = promotion_gate_repo.guarded_by_dataset

    async def pause_check(
        db: AsyncSession, dataset_id: UUID, *, organization_id: UUID
    ) -> list[AgentEnvironment]:
        guards = await original(db, dataset_id, organization_id=organization_id)
        checked.set()
        await release.wait()
        return guards

    monkeypatch.setattr(promotion_gate_repo, "guarded_by_dataset", pause_check)

    async def remove() -> bool:
        async with _session(sessions) as db:
            try:
                await DatasetService(db).delete(world.ctx, world.dataset)
                await db.commit()
                return True
            except EvalSuiteInUseError:
                await db.rollback()
                return False

    async def attach() -> bool:
        async with _session(sessions) as db:
            process = await db.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(process, int)
            await processes.put(process)
            try:
                await AgentEnvironmentService(db).update(
                    world.ctx,
                    world.agent,
                    world.environment,
                    EnvironmentUpdate(guard_suite_ids=[world.suite]),
                )
                await db.commit()
                return True
            except BadRequestError, NotFoundError:
                await db.rollback()
                return False

    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        deletion = group.create_task(remove())
        await checked.wait()
        attachment = group.create_task(attach())
        process = await processes.get()
        async with _session(sessions) as observer:
            while True:
                blocked = await observer.scalar(
                    text("SELECT pg_blocking_pids(:pid) <> '{}'::int[]"), {"pid": process}
                )
                if blocked or attachment.done():
                    break
                await asyncio.sleep(0.01)
        release.set()
    assert deletion.result() != attachment.result()
    async with _session(sessions) as db:
        exists = await db.scalar(select(Dataset.id).where(Dataset.id == world.dataset))
        assert (exists is not None) is attachment.result()


async def test_busy_agent_defers_automatic_follow_without_aborting_its_transaction(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    world = await _prepared(sessions)
    _passing(monkeypatch, world)
    async with _session(sessions) as one, _session(sessions) as two:
        agent = await agent_repo.get(one, world.agent, organization_id=world.ctx.organization_id)
        environment = await agent_environment_repo.get(
            one, world.environment, organization_id=world.ctx.organization_id
        )
        candidate = await agent_repo.get_version(
            one, world.second, organization_id=world.ctx.organization_id
        )
        assert agent is not None and environment is not None and candidate is not None
        await AgentEnvironmentService(two).get_environment(
            world.ctx, world.agent, world.environment
        )
        async with asyncio.timeout(5):
            assert await PromotionGateService(one)._advance(agent, environment, candidate) is False
        await two.commit()
        assert await PromotionGateService(one)._advance(agent, environment, candidate) is True
        await one.commit()


async def test_trying_to_lock_a_removed_agent_returns_no_row(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    world = await _prepared(sessions)
    async with _session(sessions) as db:
        assert (
            await agent_repo.try_lock(db, UUID(int=0), organization_id=world.ctx.organization_id)
            is None
        )


@pytest.mark.parametrize("overlap", [False, True])
async def test_api_guard_replacements_already_serialize_on_the_agent(
    engine: AsyncEngine, overlap: bool
) -> None:
    from tests.integration.test_eval_suites import _suite_data

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    world = await _prepared(sessions)
    async with _session(sessions) as db:
        dataset = await DatasetService(db).get(world.ctx, world.dataset)
        left = await EvalSuiteService(db).create(world.ctx, world.agent, _suite_data(dataset))
        right = await EvalSuiteService(db).create(world.ctx, world.agent, _suite_data(dataset))
        await db.commit()
    wanted_left = [left.id, right.id] if overlap else [left.id]
    wanted_right = [right.id]
    ready = asyncio.Barrier(2)

    async def replace(wanted: list[UUID]) -> None:
        async with _session(sessions) as db:
            stale = await agent_environment_repo.get(
                db, world.environment, organization_id=world.ctx.organization_id
            )
            await ready.wait()
            await AgentEnvironmentService(db).update(
                world.ctx, world.agent, world.environment, EnvironmentUpdate(guard_suite_ids=wanted)
            )
            assert stale is not None and stale.id == world.environment
            await db.commit()

    async with asyncio.timeout(10), asyncio.TaskGroup() as group:
        group.create_task(replace(wanted_left))
        group.create_task(replace(wanted_right))
    async with _session(sessions) as db:
        guards = await promotion_gate_repo.guards_for(
            db, [world.environment], organization_id=world.ctx.organization_id
        )
        assert frozenset(guards[world.environment]) in {
            frozenset(wanted_left),
            frozenset(wanted_right),
        }
