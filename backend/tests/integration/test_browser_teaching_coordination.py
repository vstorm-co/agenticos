"""PostgreSQL proof that every teaching kind shares one live-view claim."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.browser_procedure_teaching import BrowserProcedureTeachingReason
from app.core.browser_teaching import TeachingConflict, TeachingReason
from app.core.exceptions import ConflictError
from app.db.models.browser_procedure_teaching import (
    BrowserProcedureTeachingPreference,
    BrowserProcedureTeachingSession,
)
from app.db.models.browser_teaching import BrowserTeachingSession
from app.repositories import browser_teaching_view
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingStart
from app.schemas.browser_teaching import TeachingStart
from app.services.browser_procedure_teaching import _refinement
from app.services.browser_procedure_teaching import _service as procedure_service
from app.services.browser_procedure_teaching._lease import (
    BrowserProcedureTeachingIdentity,
    BrowserProcedureTeachingTakeover,
)
from app.services.browser_procedure_teaching._service import BrowserProcedureTeachingService
from app.services.browser_teaching._hold import Hold
from app.services.browser_teaching._service import BrowserTeachingService
from tests.integration.test_browser_procedure_teaching import teaching as teaching
from tests.integration.test_personal_coding_accounts import organization, person
from tests.test_browser_procedure_teaching_contracts import ORIGIN

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _enable_procedure_teaching(t) -> None:
    # The rich fixture already seeds the shared organization policy. Refinement
    # additionally needs its explicit, per-agent preference row.
    t.db.add(
        BrowserProcedureTeachingPreference(
            organization_id=t.org.id,
            user_id=t.owner.id,
            agent_id=t.agent.id,
            enabled=True,
            generation=uuid4(),
        )
    )
    await t.db.flush()


def _quick_hold(t, call_id: str) -> Hold:
    return Hold(
        organization_id=t.org.id,
        run_id=t.run.id,
        agent_id=t.agent.id,
        user_id=t.owner.id,
        call_id=call_id,
        tab_id="main",
        hold_id=uuid4(),
    )


def _procedure_hold(t, call_id: str) -> BrowserProcedureTeachingTakeover:
    return BrowserProcedureTeachingTakeover(
        organization_id=t.org.id,
        run_id=t.run.id,
        agent_id=t.agent.id,
        user_id=t.owner.id,
        controller_id=uuid4(),
        tab_id="main",
        call_id=call_id,
        connection_id=uuid4(),
        takeover_id=uuid4(),
    )


async def _start_kind(
    kind: str,
    db: AsyncSession,
    t,
    call_id: str,
    quick_hold: Hold,
    procedure_hold: BrowserProcedureTeachingTakeover,
    monkeypatch: pytest.MonkeyPatch,
):
    if kind == "simple":
        service = BrowserTeachingService(db, t.redis)

        async def live_hold(organization_id, user_id, run_id, requested_call_id):
            assert (organization_id, user_id, run_id, requested_call_id) == (
                t.org.id,
                t.owner.id,
                t.run.id,
                call_id,
            )
            return quick_hold

        service._live_hold = live_hold
        return await service.start(
            t.ctx,
            TeachingStart(
                run_id=t.run.id,
                call_id=call_id,
                title="Coordination proof",
                allowed_origins=(ORIGIN,),
            ),
            request_key=str(uuid4()),
        )

    if kind == "manual":

        async def discover(_redis, run_id, requested_call_id):
            assert (run_id, requested_call_id) == (t.run.id, call_id)
            return procedure_hold

        monkeypatch.setattr(procedure_service, "discover", discover)
        return await BrowserProcedureTeachingService(db, t.redis).start(
            t.ctx,
            BrowserProcedureTeachingStart(
                request_id=uuid4(),
                run_id=t.run.id,
                call_id=call_id,
                tab_id=procedure_hold.tab_id,
                takeover_id=procedure_hold.takeover_id,
                title="Coordination proof",
                allowed_origins=(ORIGIN,),
            ),
        )

    assert kind == "refinement"
    identity = BrowserProcedureTeachingIdentity(
        organization_id=t.org.id,
        run_id=t.run.id,
        agent_id=t.agent.id,
        user_id=t.owner.id,
        controller_id=procedure_hold.controller_id,
        tab_id=procedure_hold.tab_id,
        call_id=call_id,
    )
    return await _refinement.start(db, t.ctx, identity, ORIGIN)


def _assert_loser(kind: str, result: object) -> None:
    if kind == "simple":
        assert isinstance(result, TeachingConflict)
        assert result.reason == TeachingReason.ALREADY_RECORDING
    elif kind == "manual":
        assert isinstance(result, ConflictError)
        assert result.details == {
            "reason_code": BrowserProcedureTeachingReason.ALREADY_ACTIVE.value
        }
    else:
        assert kind == "refinement"
        assert result is None


@pytest.mark.parametrize(
    ("first_kind", "second_kind"),
    [
        ("simple", "manual"),
        ("manual", "simple"),
        ("simple", "refinement"),
        ("refinement", "simple"),
        ("manual", "refinement"),
        ("refinement", "manual"),
    ],
    ids=[
        "simple-wins-manual-loses",
        "manual-wins-simple-loses",
        "simple-wins-refinement-loses",
        "refinement-wins-simple-loses",
        "manual-wins-refinement-loses",
        "refinement-wins-manual-loses",
    ],
)
async def test_capture_starts_serialize_across_independent_transactions(
    teaching, engine, monkeypatch, first_kind, second_kind
):
    """Pause the first transaction after its advisory lock; the second must wait."""
    t = teaching
    await _enable_procedure_teaching(t)
    await t.db.commit()  # Both transactions must see committed policy, run and membership rows.
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    call_id = f"shared-view-{uuid4().hex}"
    quick_hold = _quick_hold(t, call_id)
    procedure_hold = _procedure_hold(t, call_id)

    original_lock = browser_teaching_view.lock_view_and_check_active
    first_has_lock = asyncio.Event()
    second_at_lock = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    lock_calls = 0
    first_active_results: list[bool] = []
    later_active_results: list[bool] = []
    connection_pids: list[int] = []

    async def coordinated_lock(db, organization_id, run_id, requested_call_id):
        nonlocal lock_calls
        lock_calls += 1
        call_number = lock_calls
        pid = await db.scalar(text("SELECT pg_backend_pid()"))
        assert pid is not None
        connection_pids.append(pid)
        if call_number == 1:
            active = await original_lock(db, organization_id, run_id, requested_call_id)
            first_active_results.append(active)
            first_has_lock.set()
            await release_first.wait()
            return active
        if call_number == 2:
            second_at_lock.set()
        active = await original_lock(db, organization_id, run_id, requested_call_id)
        later_active_results.append(active)
        return active

    monkeypatch.setattr(browser_teaching_view, "lock_view_and_check_active", coordinated_lock)

    async def committed_start(kind: str, *, started: asyncio.Event | None = None):
        async with sessions() as db:
            if started is not None:
                started.set()
            result = await _start_kind(
                kind, db, t, call_id, quick_hold, procedure_hold, monkeypatch
            )
            await db.commit()
            return result

    first = asyncio.create_task(committed_start(first_kind))
    second = None
    try:
        await asyncio.wait_for(first_has_lock.wait(), timeout=5)
        second = asyncio.create_task(committed_start(second_kind, started=second_started))
        await asyncio.wait_for(second_started.wait(), timeout=5)
        if {first_kind, second_kind} == {"manual", "refinement"}:
            # Both rich starts first lock their organization's policy row; the
            # second reaches the shared-view mutex after the first commits.
            await asyncio.sleep(0.05)
        else:
            await asyncio.wait_for(second_at_lock.wait(), timeout=5)
        await asyncio.sleep(0.05)
        assert not second.done(), "the second start passed the held PostgreSQL advisory lock"
    finally:
        release_first.set()
        tasks = [first] if second is None else [first, second]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    assert lock_calls == 2
    assert len(set(connection_pids)) == 2
    assert first_active_results == [False]
    assert later_active_results == [True]
    first_result, second_result = outcomes
    assert not isinstance(first_result, BaseException) and first_result is not None
    _assert_loser(second_kind, second_result)

    async with sessions() as verify:
        quick_count = await verify.scalar(
            select(func.count())
            .select_from(BrowserTeachingSession)
            .where(
                BrowserTeachingSession.organization_id == t.org.id,
                BrowserTeachingSession.run_id == t.run.id,
                BrowserTeachingSession.call_id == call_id,
                BrowserTeachingSession.status.in_(("recording", "paused")),
            )
        )
        procedure_count = await verify.scalar(
            select(func.count())
            .select_from(BrowserProcedureTeachingSession)
            .where(
                BrowserProcedureTeachingSession.organization_id == t.org.id,
                BrowserProcedureTeachingSession.run_id == t.run.id,
                BrowserProcedureTeachingSession.call_id == call_id,
                BrowserProcedureTeachingSession.status.in_(("recording", "paused")),
            )
        )
    assert (quick_count or 0) + (procedure_count or 0) == 1
    assert (quick_count or 0) == (1 if first_kind == "simple" else 0)


async def test_shared_view_check_keeps_tenant_scope_for_all_start_kinds(
    teaching, engine, monkeypatch
):
    t = teaching
    await _enable_procedure_teaching(t)
    other_owner = await person(t.db)
    other_org = await organization(t.db, other_owner)
    await t.db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    for kind in ("simple", "manual", "refinement"):
        call_id = f"tenant-view-{kind}-{uuid4().hex}"
        quick_hold = _quick_hold(t, call_id)
        procedure_hold = _procedure_hold(t, call_id)
        async with sessions() as db:
            result = await _start_kind(
                kind, db, t, call_id, quick_hold, procedure_hold, monkeypatch
            )
            assert result is not None
            await db.commit()

        # The same run/call under a different real tenant must not see tenant A's
        # active row. The helper is tested directly here because service auth
        # correctly refuses a run/organization mismatch before coordination.
        async with sessions() as db:
            assert not await browser_teaching_view.lock_view_and_check_active(
                db, other_org.id, t.run.id, call_id
            )
            await db.rollback()

        async with sessions() as db:
            assert await browser_teaching_view.lock_view_and_check_active(
                db, t.org.id, t.run.id, call_id
            )
            await db.rollback()
