"""The eval suite sweep: four steps a tick, each in a transaction of its own."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker.tasks import eval_suite_tasks

pytestmark = pytest.mark.anyio


async def test_a_tick_schedules_starts_settles_and_follows_in_four_transactions() -> None:
    sessions: list[MagicMock] = []

    @asynccontextmanager
    async def session():
        db = MagicMock()
        sessions.append(db)
        yield db

    service = MagicMock()
    service.fire_schedules = AsyncMock(return_value=1)
    service.start_due = AsyncMock(return_value=2)
    service.settle_finished = AsyncMock(return_value=3)
    service.reconcile_followers = AsyncMock(return_value=4)
    with (
        patch.object(eval_suite_tasks, "get_worker_db_context", session),
        patch("app.services.change_feed.connect_in_worker", AsyncMock()) as connect,
        patch("app.services.eval_suite.EvalSuiteService", return_value=service) as built,
    ):
        counts = await eval_suite_tasks.check_eval_suites()

    assert counts == {"fired": 1, "started": 2, "settled": 3, "followed": 4}
    assert [call.args[0] for call in built.call_args_list] == sessions
    assert len(sessions) == 4
    connect.assert_awaited_once()


async def test_a_step_that_fails_is_logged_and_the_next_still_runs() -> None:
    @asynccontextmanager
    async def session():
        yield MagicMock()

    service = MagicMock()
    service.fire_schedules = AsyncMock(side_effect=RuntimeError("cron"))
    service.start_due = AsyncMock(return_value=0)
    service.settle_finished = AsyncMock(return_value=2)
    service.reconcile_followers = AsyncMock(return_value=0)
    with (
        patch.object(eval_suite_tasks, "get_worker_db_context", session),
        patch("app.services.change_feed.connect_in_worker", AsyncMock()),
        patch("app.services.eval_suite.EvalSuiteService", return_value=service),
        patch.object(eval_suite_tasks.logger, "exception") as logged,
    ):
        counts = await eval_suite_tasks.check_eval_suites()

    assert counts == {"fired": 0, "started": 0, "settled": 2, "followed": 0}
    logged.assert_called_once()
