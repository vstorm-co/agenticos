from sqlalchemy.exc import DBAPIError

from app.worker.jobs import RUN_EVAL, SettleLater

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
from app.repositories import agent_run_repo, authoring_repo, eval_run_repo
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


class TestAbandonedEvals:
    async def test_runs_and_attempts_idle_past_the_setting_are_closed(self, monkeypatch):
        fail = AsyncMock(return_value=[MagicMock()])
        close = AsyncMock(return_value=2)
        monkeypatch.setattr(eval_run_repo, "fail_abandoned", fail)
        monkeypatch.setattr(eval_run_repo, "close_orphaned_attempts", close)
        monkeypatch.setattr(run_reaper.NotificationService, "eval_run_finished", AsyncMock())
        monkeypatch.setattr(run_reaper.settings, "EVAL_ABANDONED_AFTER_MINUTES", 30.0)

        before = datetime.now(UTC)
        assert await RunReaperService(MagicMock()).reap_abandoned_evals() == 3
        after = datetime.now(UTC)

        asked = fail.await_args.kwargs
        window = timedelta(minutes=30)
        assert before - window <= asked["idle_since"] <= after - window
        assert asked["job_kind"] == RUN_EVAL.kind
        assert before <= asked["now"] <= after
        assert close.await_args.kwargs["ended_before"] == asked["idle_since"]

    async def test_zero_switches_it_off(self, monkeypatch):
        fail = AsyncMock()
        close = AsyncMock()
        monkeypatch.setattr(eval_run_repo, "fail_abandoned", fail)
        monkeypatch.setattr(eval_run_repo, "close_orphaned_attempts", close)
        monkeypatch.setattr(run_reaper.NotificationService, "eval_run_finished", AsyncMock())
        monkeypatch.setattr(run_reaper.settings, "EVAL_ABANDONED_AFTER_MINUTES", 0.0)

        assert await RunReaperService(MagicMock()).reap_abandoned_evals() == 0
        fail.assert_not_awaited()
        close.assert_not_awaited()


class TestLostJobs:
    """A job that ended for good closes what it was running, at once."""

    async def test_a_withdrawn_eval_job_cancels_its_run(self, monkeypatch):
        cancel, fail = AsyncMock(return_value=True), AsyncMock()
        monkeypatch.setattr(eval_run_repo, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(eval_run_repo, "cancel_live", cancel)
        monkeypatch.setattr(eval_run_repo, "fail_live", fail)
        run, org = uuid.uuid4(), uuid.uuid4()

        await RunReaperService(MagicMock()).settle_lost_eval(
            run, organization_id=org, why="cancelled"
        )

        assert cancel.await_args.args[1] == run
        assert cancel.await_args.kwargs["organization_id"] == org
        fail.assert_not_awaited()

    @pytest.mark.parametrize(
        "why", ["timed out after 12:00:00; the job was cancelled", "worker killed"]
    )
    async def test_any_other_end_fails_the_run_with_a_sentence_of_its_own(self, monkeypatch, why):
        """The job's last error is the worker's; the run's page gets this module's words."""
        cancel, fail = AsyncMock(), AsyncMock(return_value=True)
        monkeypatch.setattr(eval_run_repo, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(eval_run_repo, "cancel_live", cancel)
        monkeypatch.setattr(eval_run_repo, "fail_live", fail)
        org = uuid.uuid4()

        await RunReaperService(MagicMock()).settle_lost_eval(
            uuid.uuid4(), organization_id=org, why=why
        )

        cancel.assert_not_awaited()
        assert fail.await_args.kwargs["organization_id"] == org
        assert fail.await_args.kwargs["error"] == (
            "This eval's job ended before the run did. Run it again."
        )

    async def test_a_run_its_worker_closed_says_nothing(self, monkeypatch, caplog):
        monkeypatch.setattr(eval_run_repo, "fail_live", AsyncMock(return_value=False))

        with caplog.at_level("WARNING", logger="app.services.run_reaper"):
            await RunReaperService(MagicMock()).settle_lost_eval(
                uuid.uuid4(), organization_id=uuid.uuid4(), why="dead"
            )

        assert not [r for r in caplog.records if r.message == "eval_run_job_lost"]

    @pytest.mark.parametrize(
        ("why", "error"),
        [
            ("cancelled", "The request was cancelled before it started. Try again."),
            ("worker killed", "The assistant stopped without finishing. Try again."),
        ],
    )
    async def test_a_lost_authoring_job_fails_its_request(
        self, monkeypatch, caplog, why: str, error: str
    ):
        fail = AsyncMock(return_value=True)
        monkeypatch.setattr(authoring_repo, "fail_unfinished", fail)
        request, org = uuid.uuid4(), uuid.uuid4()

        with caplog.at_level("WARNING", logger="app.services.run_reaper"):
            await RunReaperService(MagicMock()).settle_lost_authoring(
                request, organization_id=org, why=why
            )

        assert fail.await_args.args[1] == request
        assert fail.await_args.kwargs["organization_id"] == org
        assert fail.await_args.kwargs["error"] == error
        assert [r for r in caplog.records if r.message == "authoring_request_job_lost"]

    async def test_a_request_a_worker_still_holds_is_settled_later(self, monkeypatch):
        class Locked(Exception):
            sqlstate = "55P03"

        monkeypatch.setattr(
            authoring_repo,
            "fail_unfinished",
            AsyncMock(side_effect=DBAPIError("SELECT", {}, Locked("locked"))),
        )

        with pytest.raises(SettleLater):
            await RunReaperService(MagicMock()).settle_lost_authoring(
                uuid.uuid4(), organization_id=uuid.uuid4(), why="dead"
            )

    async def test_any_other_database_error_is_not_mistaken_for_a_held_row(self, monkeypatch):
        class Down(Exception):
            sqlstate = "08006"

        monkeypatch.setattr(
            authoring_repo,
            "fail_unfinished",
            AsyncMock(side_effect=DBAPIError("SELECT", {}, Down("down"))),
        )

        with pytest.raises(DBAPIError):
            await RunReaperService(MagicMock()).settle_lost_authoring(
                uuid.uuid4(), organization_id=uuid.uuid4(), why="dead"
            )

    async def test_a_finished_request_says_nothing(self, monkeypatch, caplog):
        monkeypatch.setattr(authoring_repo, "fail_unfinished", AsyncMock(return_value=False))

        with caplog.at_level("WARNING", logger="app.services.run_reaper"):
            await RunReaperService(MagicMock()).settle_lost_authoring(
                uuid.uuid4(), organization_id=uuid.uuid4(), why="dead"
            )

        assert not [r for r in caplog.records if r.message == "authoring_request_job_lost"]
