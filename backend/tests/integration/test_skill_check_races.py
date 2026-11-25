"""Two people deciding one check at once, each in a session of their own."""

import asyncio
import contextlib

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import AlreadyExistsError, AppException
from app.db.models.skill_check import SkillCheck
from app.db.models.skill_proposal import SkillProposal
from app.repositories import skill_check_repo
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill_check import SkillCheckApply, SkillCheckStart
from app.services.skill_check import SkillCheckService
from app.services.skill_proposal import SkillProposalService
from tests.integration.test_skill_check_edges import _proposal
from tests.integration.test_skill_checks import FakeEvals, Outcome, _lab, _run_to_end, _start

pytestmark = pytest.mark.anyio


async def _waiting_for_a_lock(
    factory: async_sessionmaker[AsyncSession], task: asyncio.Task[object]
) -> None:
    """Return once some session of this database waits for a lock; a task that ends first
    is awaited, so its own outcome is what fails the test."""
    async with factory() as session:
        for _ in range(600):
            if task.done():
                await task
                raise AssertionError("the decision finished without waiting for a lock")
            waiting = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            )
            if waiting:
                return
            # pg_stat_activity is read once per transaction and repeated until it ends.
            await session.rollback()
            await asyncio.sleep(0.1)
    raise AssertionError("nothing waited for a lock within 60s")


async def test_a_check_discarded_while_an_apply_waited_is_not_applied(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    """The apply reads the check, waits for its lock, and must then see the discard."""
    lab = await _lab(db)
    evals = FakeEvals()
    evals.install(monkeypatch)
    service = SkillCheckService(db)
    started = await service.start(lab.ctx, lab.skill.id, _start())
    evals.outcomes = {lab.a.id: Outcome(fixed=1)}
    await _run_to_end(service, evals, lab, started.id)
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def apply() -> object:
        async with factory() as session:
            return await SkillCheckService(session).apply(
                lab.ctx, lab.skill.id, started.id, SkillCheckApply(acknowledge_unknown=True)
            )

    task: asyncio.Task[object] | None = None
    async with factory() as discarding:
        try:
            await SkillCheckService(discarding).discard(lab.ctx, lab.skill.id, started.id)
            task = asyncio.create_task(apply())
            await _waiting_for_a_lock(factory, task)

            await discarding.commit()
            with pytest.raises(AlreadyExistsError):
                await task
            task = None
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async with factory() as reading:
        check = await reading.get(SkillCheck, started.id)
        assert check is not None and (check.status, check.outcome) == ("discarded", "discard")


async def test_a_check_cancelled_while_its_proposal_closed_keeps_the_cancel(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    """Closing the proposal reads its check running, waits for the cancel's lock, and must
    then leave the cancelled check as it is rather than stop it a second time."""
    lab = await _lab(db)
    FakeEvals().install(monkeypatch)
    proposal = await _proposal(db, lab)
    started = await SkillCheckService(db).start(
        lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
    )
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def close_proposal() -> object:
        async with factory() as session:
            await SkillCheckService(session).stop_for_proposal(lab.ctx, lab.skill.id, proposal.id)
            await session.commit()
        return None

    task: asyncio.Task[object] | None = None
    async with factory() as cancelling:
        try:
            cancelled = await SkillCheckService(cancelling).cancel(
                lab.ctx, lab.skill.id, started.id
            )
            task = asyncio.create_task(close_proposal())
            await _waiting_for_a_lock(factory, task)

            await cancelling.commit()
            await task
            task = None
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async with factory() as reading:
        check = await reading.get(SkillCheck, started.id)
        assert check is not None and check.status == "cancelled"
        assert check.finished_at == cancelled.finished_at


async def test_a_check_and_its_proposal_discarded_at_once_do_not_deadlock(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    """Both discards lock the proposal before the check. Paused just after the check's
    discard holds the check, the proposal's discard then waits for it rather than taking
    the proposal first and waiting on the check, which is the cycle Postgres aborts."""
    lab = await _lab(db)
    FakeEvals().install(monkeypatch)
    proposal = await _proposal(db, lab)
    started = await SkillCheckService(db).start(
        lab.ctx, lab.skill.id, SkillCheckStart(proposal_id=proposal.id)
    )
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    holding, go = asyncio.Event(), asyncio.Event()
    get = skill_check_repo.get
    first_lock = [True]

    async def pausing(db_: AsyncSession, check_id, **kwargs):
        found = await get(db_, check_id, **kwargs)
        if kwargs.get("lock") and check_id == started.id and first_lock[0]:
            first_lock[0] = False
            holding.set()
            await go.wait()
        return found

    monkeypatch.setattr(skill_check_repo, "get", pausing)

    async def discard_check() -> None:
        async with factory() as session:
            await SkillCheckService(session).discard(lab.ctx, lab.skill.id, started.id)
            await session.commit()

    async def discard_proposal() -> str:
        async with factory() as session:
            try:
                await SkillProposalService(session).discard(
                    lab.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
                )
            except AppException as refused:
                assert refused.status_code == 409, refused
                return "refused"
            await session.commit()
            return "discarded"

    tasks: list[asyncio.Task[object]] = []
    try:
        tasks.append(asyncio.create_task(discard_check()))
        await holding.wait()
        tasks.append(asyncio.create_task(discard_proposal()))
        await _waiting_for_a_lock(factory, tasks[1])
        go.set()
        await tasks[0]
        assert await tasks[1] in ("refused", "discarded")
        tasks = []
    finally:
        go.set()
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async with factory() as reading:
        check = await reading.get(SkillCheck, started.id)
        stored = await reading.get(SkillProposal, proposal.id)
        assert check is not None and check.status == "discarded"
        assert stored is not None and stored.status == "discarded"
