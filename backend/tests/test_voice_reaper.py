"""Calls a dead process left on the provider's bill (#54, Q3)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.db.models.voice_call import VoiceCall
from app.services.voice.reaper import VoiceCallReaper

pytestmark = pytest.mark.anyio
_M = "app.services.voice.reaper"
_NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _row(**overrides):
    values = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "run_id": uuid4(),
        "transport": "webrtc",
        "provider": "openai",
        "provider_call_id": "rtc_1",
        "secret_id": uuid4(),
        "started_at": _NOW - timedelta(minutes=5),
        "heartbeat_at": _NOW - timedelta(minutes=2),
        "ended_at": None,
        "end_reason": None,
        "cost_usd": Decimal("0.40"),
        "seconds": 180,
        "guardrail_hits": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Sessions:
    """A session factory that counts what each session did: committed, or rolled back."""

    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    @asynccontextmanager
    async def __call__(self):
        try:
            yield MagicMock()
        except Exception:
            self.rolled_back += 1
            raise
        self.committed += 1


async def _reap(rows, *, hung=True, claimed=None, sessions=None):
    by_id = {row.id: row for row in rows}
    with (
        patch(f"{_M}.voice_call_repo.list_unhung", AsyncMock(return_value=rows)),
        patch(
            f"{_M}.voice_call_repo.claim_unhung",
            AsyncMock(side_effect=claimed or (lambda db, call_id, **kw: by_id[call_id])),
        ),
        patch(f"{_M}.voice_call_repo.end", AsyncMock()) as ended,
        patch(f"{_M}.voice_call_repo.mark_hung_up", AsyncMock()) as marked,
        patch(
            f"{_M}.hang_up_row",
            AsyncMock(side_effect=hung if callable(hung) else lambda db, row: hung),
        ) as hang,
        patch(f"{_M}.agent_run_repo.close_voice_run", AsyncMock(return_value=True)) as closed,
        patch(
            f"{_M}.agent_run_repo.expire_pending_approvals", AsyncMock(return_value=1)
        ) as expired,
    ):
        count = await VoiceCallReaper(sessions or _Sessions()).reap(now=_NOW)
    return count, SimpleNamespace(
        ended=ended, marked=marked, hang=hang, closed=closed, expired=expired
    )


async def test_a_call_whose_heartbeat_stopped_is_hung_up_and_its_run_closed():
    row = _row()
    count, seen = await _reap([row])

    assert count == 1
    assert seen.hang.await_args.args[1] is row
    assert seen.ended.await_args.kwargs["reason"].value == "reaped"
    # What the row recorded stands: the reaper knows nothing the call did not write.
    assert seen.ended.await_args.kwargs["guardrail_hits"] == 2
    seen.marked.assert_awaited_once()
    closed = seen.closed.await_args.kwargs
    assert (
        closed["run_id"] == row.run_id
        and closed["cost_usd"] == Decimal("0.40")
        and closed["status"] == "failed"
    )
    seen.expired.assert_awaited_once()


async def test_a_hang_up_that_fails_is_left_for_the_next_sweep():
    _, seen = await _reap([_row()], hung=False)
    seen.marked.assert_not_awaited()


async def test_an_ended_call_whose_hang_up_failed_is_retried_and_its_run_left_to_its_outcome():
    """The row already says how it ended; only a run nothing closed is closed, and only
    while it is still `running` (`close_voice_run` touches no other)."""
    _, seen = await _reap([_row(ended_at=_NOW - timedelta(minutes=1), end_reason="user")])
    seen.hang.assert_awaited_once()
    seen.ended.assert_not_awaited()
    assert seen.closed.await_args.kwargs["status"] == "failed"


async def test_a_connection_a_reconnect_took_over_is_closed_as_continued_not_failed():
    _, seen = await _reap([_row(ended_at=_NOW - timedelta(minutes=1), end_reason="disconnected")])
    closed = seen.closed.await_args.kwargs
    assert (closed["status"], closed["error"]) == ("cancelled", None)


@pytest.mark.security
async def test_an_ended_calls_pending_approvals_are_expired():
    _, seen = await _reap([_row(ended_at=_NOW - timedelta(minutes=1), end_reason="error")])
    assert seen.expired.await_args.kwargs["run_id"] is not None


async def test_a_call_that_cannot_be_hung_up_is_abandoned_after_an_hour():
    """Its key is gone: retrying it for ever would hold the head of the oldest-first queue."""
    row = _row(started_at=_NOW - timedelta(minutes=61))
    count, seen = await _reap([row], hung=False)
    assert count == 0
    assert seen.ended.await_args.kwargs["reason"].value == "abandoned"
    seen.marked.assert_awaited_once()


async def test_a_call_that_cannot_be_hung_up_yet_is_retried_within_the_hour():
    _, seen = await _reap([_row(started_at=_NOW - timedelta(minutes=30))], hung=False)
    assert seen.ended.await_args.kwargs["reason"].value == "reaped"
    seen.marked.assert_not_awaited()


@pytest.mark.parametrize("reaped", [0, 2])
async def test_the_sweep_runs_the_reaper_on_sessions_of_its_own(reaped):
    from app.worker.tasks.voice_tasks import voice_call_sweep_flow

    reaper = MagicMock(reap=AsyncMock(return_value=reaped))
    with (
        patch("app.worker.tasks.voice_tasks.get_worker_db_context") as ctx,
        patch("app.worker.tasks.voice_tasks.VoiceCallReaper", return_value=reaper) as made,
    ):
        assert await voice_call_sweep_flow() == reaped

    assert made.call_args.args == (ctx,)
    reaper.reap.assert_awaited_once()


async def test_a_call_with_no_run_left_is_still_ended_and_hung_up():
    count, seen = await _reap([_row(run_id=None)])
    assert count == 1
    seen.ended.assert_awaited_once()
    seen.closed.assert_not_awaited()


async def test_a_row_that_cannot_be_closed_does_not_stop_the_sweep_or_undo_the_others():
    """Each row commits on its own: a raise on one rolls back that row only, and the
    rows after it are still hung up (RR-c01)."""
    broken, first, last = _row(), _row(), _row()

    def hang(db, row):
        if row is broken:
            raise RuntimeError("the database went away mid-row")
        return True

    sessions = _Sessions()
    count, seen = await _reap([first, broken, last], hung=hang, sessions=sessions)

    assert count == 2
    assert {call.args[1] for call in seen.marked.await_args_list} == {first.id, last.id}
    # The listing's session, the two closed rows' - and the broken row's, rolled back.
    assert (sessions.committed, sessions.rolled_back) == (3, 1)


async def test_a_row_another_sweep_holds_is_skipped():
    held, free = _row(), _row()

    async def claim(db, call_id, **kw):
        return None if call_id == held.id else free

    count, seen = await _reap([held, free], claimed=claim)

    assert count == 1
    assert [call.args[1] for call in seen.hang.await_args_list] == [free]


def test_a_call_row_names_itself_in_logs_by_id_provider_and_end():
    call_id = uuid4()
    row = VoiceCall(id=call_id, provider="openai", ended_at=None)

    assert repr(row) == f"<VoiceCall(id={call_id}, provider=openai, ended_at=None)>"
