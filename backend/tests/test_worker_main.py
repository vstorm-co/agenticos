"""The worker process's start-up: what it sets up once, before it serves (#2219).

A fired routine is an agent run in a process that ran none of the API's
startup. Each Prefect flow run used to set itself up; the worker does it once,
for every job it will run: redaction and tracing before anything logs (#440,
#1700), and the Redis clients a run publishes its Activity, its live browse
view and its browse plans on (#2099, #2128).
"""

from collections.abc import Coroutine
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker import __main__ as worker_main
from app.worker.executors import ChildPool, InProcessExecutor
from app.worker.jobs import Pool

pytestmark = pytest.mark.anyio


def test_pools_are_read_from_a_comma_list_and_a_wrong_name_is_refused() -> None:
    assert worker_main.pools_from(" agent , ingest ") == [Pool.AGENT, Pool.INGEST]
    with pytest.raises(ValueError, match="at least one pool"):
        worker_main.pools_from(" , ")
    with pytest.raises(ValueError):
        worker_main.pools_from("agent,gpu")


def test_ingestion_runs_in_child_processes_and_the_rest_on_the_loop() -> None:
    executors = worker_main.executors_for([Pool.AGENT, Pool.INGEST, Pool.SYSTEM])
    assert isinstance(executors[Pool.INGEST], ChildPool)
    assert isinstance(executors[Pool.AGENT], InProcessExecutor)
    assert isinstance(executors[Pool.SYSTEM], InProcessExecutor)

    ingest = executors[Pool.INGEST]
    assert isinstance(ingest, ChildPool)
    assert ingest.handlers == "app.worker.handlers:ingest"


def test_a_worker_serving_only_ingestion_loads_no_handler_itself() -> None:
    with patch.object(worker_main, "production") as production:
        executors = worker_main.executors_for([Pool.INGEST])
    production.assert_not_called()
    assert list(executors) == [Pool.INGEST]


def test_the_ingest_handlers_are_exactly_the_ingest_pools_kinds() -> None:
    from app.worker import handlers, jobs

    assert set(handlers.ingest()) == {
        task.kind for task in jobs.TASKS.values() if task.pool is Pool.INGEST
    }
    assert set(handlers.ingest()) <= set(handlers.production())


def test_main_sets_redaction_and_tracing_up_before_it_serves() -> None:
    order: list[str] = []

    def served(coroutine: Coroutine[object, object, None]) -> None:
        order.append("serve")
        coroutine.close()

    with (
        patch.object(worker_main, "setup_logging", side_effect=lambda: order.append("logging")),
        patch.object(
            worker_main, "setup_worker_observability", side_effect=lambda: order.append("tracing")
        ),
        patch.object(worker_main.asyncio, "run", side_effect=served),
        patch("sys.argv", ["app.worker", "--pools", "system"]),
    ):
        worker_main.main()

    assert order == ["logging", "tracing", "serve"]


async def test_serve_connects_what_a_fired_run_publishes_on_and_declares_the_schedules() -> None:
    worker = MagicMock()
    worker.run = AsyncMock()
    connected = {name: AsyncMock() for name in ("change_feed", "live_browse", "browse_plans")}
    declared = AsyncMock()

    class _Session:
        async def __aenter__(self) -> MagicMock:
            return MagicMock()

        async def __aexit__(self, *_: object) -> bool:
            return False

    with (
        patch("app.services.change_feed.connect_in_worker", connected["change_feed"]),
        patch("app.services.live_browse.connect_in_worker", connected["live_browse"]),
        patch("app.services.browse_plans.connect_in_worker", connected["browse_plans"]),
        patch.object(worker_main, "claim_pooled_engines") as claimed,
        patch.object(worker_main, "get_db_context", lambda: _Session()),
        patch.object(worker_main.schedules, "declare", declared),
        patch.object(worker_main, "Worker", return_value=worker) as built,
        patch.object(worker_main, "close_db", new=AsyncMock()) as closed,
    ):
        await worker_main.serve([Pool.SYSTEM])

    claimed.assert_called_once_with()
    for connect in connected.values():
        connect.assert_awaited_once_with()
    assert declared.await_args.args[1] is worker_main.schedules.SCHEDULES
    assert declared.await_args.kwargs["now"] <= datetime.now(UTC)
    settings = built.call_args.kwargs["settings"]
    assert settings.worker_id.startswith(f"{settings.hostname}:")
    worker.run.assert_awaited_once()
    closed.assert_awaited_once_with()
