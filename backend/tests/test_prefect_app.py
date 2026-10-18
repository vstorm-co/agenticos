"""The Prefect runner registers its deployments with a ceiling on concurrency."""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from prefect.client.schemas.objects import ConcurrencyLimitStrategy

from app.core.config import settings
from app.worker import prefect_app

pytestmark = pytest.mark.anyio


@pytest.fixture
def captured_runner(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stand in for the Prefect `Runner` that `aserve` builds, and record its arguments.

    `aserve` imports `Runner` from `prefect.runner` inside its own body, so that
    is where the patch has to land.
    """
    runner = MagicMock()
    runner.add_deployment = AsyncMock()
    runner.start = AsyncMock()
    factory = MagicMock(return_value=runner)
    monkeypatch.setattr("prefect.runner.Runner", factory)
    runner.factory = factory
    return runner


async def test_the_runner_refuses_to_start_more_runs_than_the_host_can_hold(
    captured_runner: MagicMock,
) -> None:
    """A backlog must queue, not fan out.

    Every flow run is a separate process importing the whole application, so the
    ceiling is memory. `aserve` declares `limit: Optional[int] = None` and passes
    it straight to `Runner`, where `None` means *no cap* - while constructing a
    `Runner` without the argument would have fallen back to Prefect's own default
    of five. Calling `aserve` and saying nothing is therefore how this runner came
    to have no ceiling: after three days of downtime it picked up the backlog of
    once-a-minute `rag-sync-check` runs, started 71 processes at once and took
    6 GiB of a 7.75 GiB host, and the kernel resolved it by OOM-killing the API.
    """
    await prefect_app.main()

    limit = captured_runner.factory.call_args.kwargs["limit"]
    assert limit == settings.PREFECT_RUNNER_LIMIT
    assert isinstance(limit, int) and limit > 0


async def test_the_runner_serves_a_health_endpoint_of_its_own(
    captured_runner: MagicMock,
) -> None:
    """Without it this container's health status is a constant, and a constant is not a status.

    The runner shares `agenticos_backend` with the API, whose image-level
    `HEALTHCHECK` asked localhost:8000 for `/api/v1/health` - nothing the runner
    serves, so it was `unhealthy` from the second it started and a runner that had
    actually died looked exactly like one that was fine. `webserver=True` starts
    Prefect's own runner server, whose `/health` answers 503 once `last_polled`
    goes stale; the compose files probe it and the image no longer carries a
    `HEALTHCHECK` at all.
    """
    await prefect_app.main()

    assert captured_runner.factory.call_args.kwargs["webserver"] is True


async def test_every_deployment_is_registered_before_the_runner_starts(
    captured_runner: MagicMock,
) -> None:
    """A deployment added after `start()` is one the runner never polls for."""
    await prefect_app.main()

    registered: list[Any] = [call.args[0] for call in captured_runner.add_deployment.call_args_list]
    assert {deployment.name for deployment in registered} == {
        "ingest-document",
        "sync-single-source",
        "sync-collection",
        "rag-sync-check",
        "run-scheduled-trigger",
        "org-purge-cleanup",
        "agent-triggers-check",
        "portal-poll",
        "sandbox-log-sweep",
        "mcp-connection-sweep",
        "approval-expiry-sweep",
        "invitation-expiry-sweep",
        "stale-run-sweep",
        "teardown-reservation-sweep",
        "retention-sweep",
        "weekly-usage-report",
        "monthly-usage-report",
        "notification-delivery-sweep",
        "notification-retention-sweep",
    }
    assert captured_runner.start.await_count == 1


async def test_a_scheduled_sweep_skips_a_tick_rather_than_queueing_it(
    captured_runner: MagicMock,
) -> None:
    """A host that falls behind must shed ticks, not stack them.

    On 2026-10-17 production fell behind its four minute-ticks: each queued tick
    was another process importing the application on a saturated CPU, so each
    one ran slower than the last, and eight hours later ~1,650 runs were Late and
    the API's workers were being starved into restarts. A sweep covers current
    state, so the tick that finds its predecessor still running is cancelled by
    the server.

    Two kinds keep no limit. The on-demand deployments, because every ingestion
    or cleanup run there is its own piece of work. And the usage reports, because
    each covers the period its run's scheduled time names: a report tick
    cancelled for overlapping would be a week or a month nobody is ever sent.
    """
    await prefect_app.main()

    registered: list[Any] = [call.args[0] for call in captured_runner.add_deployment.call_args_list]
    reports = {"weekly-usage-report", "monthly-usage-report"}
    sweeps = [d for d in registered if d.schedules and d.name not in reports]
    unlimited = [d for d in registered if not d.schedules or d.name in reports]
    assert sweeps and {d.name for d in unlimited} >= reports
    for deployment in sweeps:
        assert deployment.concurrency_limit == 1, deployment.name
        assert deployment.concurrency_options is not None, deployment.name
        assert (
            deployment.concurrency_options.collision_strategy == ConcurrencyLimitStrategy.CANCEL_NEW
        )
    for deployment in unlimited:
        assert deployment.concurrency_limit is None, deployment.name


class TestTheIntervalFloor:
    """`WORKER_MIN_INTERVAL_SECONDS` - a floor, not a multiplier.

    Every flow run is a separate Python process that imports the whole
    application, so on a laptop the four minute-ticks cost far more in imports
    than the work they do. A deployment leaves this at `0` and gets exactly the
    intervals the code declares.
    """

    def test_zero_leaves_every_declared_interval_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "WORKER_MIN_INTERVAL_SECONDS", 0)

        assert prefect_app._every(60).interval == timedelta(seconds=60)
        assert prefect_app._every(86_400).interval == timedelta(seconds=86_400)

    def test_a_floor_lengthens_only_what_is_faster_than_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole reason this is a floor. A multiplier would turn the daily
        sweeps into weeks to quieten a minute-tick, which is how a retention
        policy stops running without anybody deciding that."""
        monkeypatch.setattr(settings, "WORKER_MIN_INTERVAL_SECONDS", 600)

        assert prefect_app._every(60).interval == timedelta(seconds=600)
        assert prefect_app._every(900).interval == timedelta(seconds=900)
        assert prefect_app._every(86_400).interval == timedelta(seconds=86_400)

    def test_a_floor_below_every_interval_changes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "WORKER_MIN_INTERVAL_SECONDS", 30)

        assert prefect_app._every(60).interval == timedelta(seconds=60)
