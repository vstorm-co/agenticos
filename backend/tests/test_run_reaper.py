"""The sweep that ends runs whose process died under them (#1078).

A run's row is committed `running` before its model is called (#12), so a
process death mid-run leaves a durable row nothing in-process will ever finish.
These cover the service's own decisions - the window, the off switch, what is
said on the row; which rows the write actually touches is proved against a real
Postgres in `tests/integration/test_stale_run_reaping.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.agent_run import AgentRun
from app.repositories import agent_run_repo
from app.services import run_reaper
from app.services.run_reaper import RunReaperService
from app.worker.tasks.run_tasks import reap_stale_runs

pytestmark = pytest.mark.anyio


def _run() -> AgentRun:
    return AgentRun(id=uuid.uuid4(), organization_id=uuid.uuid4(), user_id=uuid.uuid4())


class TestTheWindow:
    async def test_the_ceiling_moves_with_the_setting(self, monkeypatch):
        fail = AsyncMock(return_value=[])
        monkeypatch.setattr(agent_run_repo, "fail_stale_runs", fail)
        monkeypatch.setattr(run_reaper.settings, "STALE_RUN_REAPED_AFTER_SECONDS", 120.0)

        before = datetime.now(UTC)
        await RunReaperService(MagicMock()).reap_stale()
        after = datetime.now(UTC)

        asked = fail.await_args.kwargs
        window = timedelta(seconds=120)
        assert before - window <= asked["older_than"] <= after - window
        assert before <= asked["ended_at"] <= after

    async def test_zero_switches_the_sweep_off(self, monkeypatch):
        """The same off switch shape as the event-loop watchdog: a breakpoint
        held longer than the ceiling must not fail the run being debugged."""
        fail = AsyncMock()
        monkeypatch.setattr(agent_run_repo, "fail_stale_runs", fail)
        monkeypatch.setattr(run_reaper.settings, "STALE_RUN_REAPED_AFTER_SECONDS", 0.0)

        assert await RunReaperService(MagicMock()).reap_stale() == []
        fail.assert_not_awaited()


class TestWhatTheRowIsTold:
    async def test_the_error_is_a_controlled_sentence_about_the_process(self, monkeypatch):
        """`agent_runs.error` is rendered in run history, so what lands there is
        this module's own sentence - never anything read off the dead process."""
        fail = AsyncMock(return_value=[_run()])
        monkeypatch.setattr(agent_run_repo, "fail_stale_runs", fail)

        reaped = await RunReaperService(MagicMock()).reap_stale()

        assert len(reaped) == 1
        error = fail.await_args.kwargs["error"]
        assert "died before recording an outcome" in error
        assert "stale-run sweep" in error

    async def test_every_reaped_run_is_named_in_the_log(self, monkeypatch, caplog):
        """The row says what happened; the log is where an operator counting
        crashes finds which runs, without a query."""
        runs = [_run(), _run()]
        monkeypatch.setattr(agent_run_repo, "fail_stale_runs", AsyncMock(return_value=runs))

        with caplog.at_level("WARNING", logger="app.services.run_reaper"):
            assert len(await RunReaperService(MagicMock()).reap_stale()) == 2

        assert sum(1 for r in caplog.records if r.message == "stale_run_reaped") == 2

    async def test_each_reaped_run_is_an_update_the_consoles_hear_of(self, monkeypatch):
        """What clears a chat's "Working" over a turn nothing is answering."""
        run = _run()
        monkeypatch.setattr(agent_run_repo, "fail_stale_runs", AsyncMock(return_value=[run]))

        (event,) = await RunReaperService(MagicMock()).reap_stale()

        assert (event.resource, event.id, event.action) == ("run", run.id, "updated")
        assert event.organization_id == run.organization_id


class TestTheFlow:
    async def test_the_sweep_runs_the_reaper_on_a_session_of_its_own(self):
        events = [MagicMock(), MagicMock(), MagicMock()]
        service = MagicMock(reap_stale=AsyncMock(return_value=events))
        order: list[str] = []

        async def committed(*_args: object) -> bool:
            order.append("commit")
            return False

        async def published(event: object) -> None:
            order.append("publish")

        with (
            patch("app.worker.tasks.run_tasks.get_worker_db_context") as ctx,
            patch("app.worker.tasks.run_tasks.RunReaperService", return_value=service),
            patch("app.worker.tasks.run_tasks.change_feed.publish", side_effect=published),
        ):
            ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            ctx.return_value.__aexit__ = committed
            assert await reap_stale_runs() == 3

        service.reap_stale.assert_awaited_once()
        # Announced only once the session that reaped them has committed: a
        # console refetching on the event must read the run as ended.
        assert order == ["commit", "publish", "publish", "publish"]
