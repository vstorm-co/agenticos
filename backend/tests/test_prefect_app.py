"""The Prefect runner registers its deployments with a ceiling on concurrency."""

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from prefect.client.schemas.objects import ConcurrencyLimitStrategy

from app.core.config import settings
from app.worker import prefect_app

pytestmark = pytest.mark.anyio

# Kept before the autouse fixture below stands a stub in for it.
_RETIRE = prefect_app.retire_minute_deployments


@pytest.fixture(autouse=True)
def sweeps(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The worker's in-process sweeps and their Redis, recorded rather than run.

    Run for real they would tick until the test was killed.
    """
    seen: dict[str, Any] = {}
    redis = MagicMock(connect=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(prefect_app, "RedisClient", MagicMock(return_value=redis))

    def run_sweeps(sweeps: Any, client: Any) -> Any:
        # Recorded at the call: the runner below returns at once, and the task is
        # cancelled before its body would have run.
        seen["sweeps"], seen["redis"] = sweeps, client
        return asyncio.sleep(0)

    monkeypatch.setattr(prefect_app, "run_sweeps", run_sweeps)
    monkeypatch.setattr(prefect_app, "retire_minute_deployments", AsyncMock())
    seen["client"] = redis
    return seen


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
        "sandbox-log-sweep",
        "mcp-connection-sweep",
        "approval-expiry-sweep",
        "invitation-expiry-sweep",
        "stale-run-sweep",
        "teardown-reservation-sweep",
        "retention-sweep",
        "weekly-usage-report",
        "monthly-usage-report",
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
    # Started on demand by its sweep, and still one at a time: the sweep comes
    # round every minute whether or not the last batch of syncs has finished.
    checks = {"rag-sync-check"}
    limited = [d for d in registered if (d.schedules and d.name not in reports) or d.name in checks]
    unlimited = [d for d in registered if d not in limited]
    assert limited and {d.name for d in unlimited} >= reports
    for deployment in limited:
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


async def test_the_minute_sweeps_run_in_this_process_beside_the_runner(
    captured_runner: MagicMock, sweeps: dict[str, Any]
) -> None:
    """As deployments, each of their ticks was a process importing the whole
    application - longer than the minute between ticks on the production host (#2213)."""
    await prefect_app.main()

    assert [(s.name, s.every_seconds) for s in sweeps["sweeps"]] == [
        ("agent-triggers-check", 60),
        ("portal-poll", 60),
        ("notification-delivery-sweep", 60),
        ("rag-sync-check", 60),
        ("sandbox-destroy-retry", 60),
    ]
    assert sweeps["redis"] is sweeps["client"]
    sweeps["client"].connect.assert_awaited_once()
    sweeps["client"].close.assert_awaited_once()
    registered = {
        call.args[0].name: call.args[0] for call in captured_runner.add_deployment.call_args_list
    }
    assert not registered["rag-sync-check"].schedules


def test_every_sweep_the_worker_runs_is_one_the_health_probe_checks() -> None:
    """A sweep added here and not there would stop with nobody told."""
    from app.services import worker_heartbeat

    assert tuple(sweep.name for sweep in prefect_app.SWEEPS) == worker_heartbeat.SWEEPS


async def test_the_sweeps_stop_when_the_runner_does(
    captured_runner: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner stopped through `/shutdown` runs nothing more, so the sweeps must
    not go on claiming triggers and submitting runs for it."""
    stopped = asyncio.Event()

    async def forever(*_: object) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopped.set()
            raise

    monkeypatch.setattr(prefect_app, "run_sweeps", forever)

    async def runs_a_while() -> None:
        await asyncio.sleep(0.05)

    captured_runner.start = AsyncMock(side_effect=runs_a_while)

    await asyncio.wait_for(prefect_app.main(), timeout=5)

    assert stopped.is_set()


class TestRetiringTheMinuteDeployments:
    """What Prefect still schedules for work the sweeps took over."""

    @staticmethod
    def _client(monkeypatch: pytest.MonkeyPatch, known: dict[str, Any]) -> MagicMock:
        from prefect.exceptions import ObjectNotFound

        client = MagicMock()

        async def read(name: str) -> Any:
            found = known.get(name)
            if found is None:
                raise ObjectNotFound(http_exc=Exception(name))
            if isinstance(found, Exception):
                raise found
            return found

        client.read_deployment_by_name = AsyncMock(side_effect=read)
        client.delete_deployment = AsyncMock()
        client.read_deployment_schedules = AsyncMock(
            return_value=[MagicMock(id="s-1"), MagicMock(id="s-2")]
        )
        client.delete_deployment_schedule = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        monkeypatch.setattr("prefect.client.orchestration.get_client", lambda: client)
        return client

    async def test_the_replaced_deployments_go_and_the_sync_check_loses_its_schedule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Left behind, each would still get a run a minute that nothing serves -
        the Late backlog the sweeps exist to end."""
        known = {name: MagicMock(id=f"d-{name}") for name in prefect_app.RETIRED_DEPLOYMENTS}
        known["rag-sync-check/rag-sync-check"] = MagicMock(id="d-sync")
        client = self._client(monkeypatch, known)

        await _RETIRE()

        assert [call.args[0] for call in client.delete_deployment.await_args_list] == [
            f"d-{name}" for name in prefect_app.RETIRED_DEPLOYMENTS
        ]
        assert [call.args for call in client.delete_deployment_schedule.await_args_list] == [
            ("d-sync", "s-1"),
            ("d-sync", "s-2"),
        ]

    async def test_a_fresh_database_with_none_of_them_is_fine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(monkeypatch, {})

        await _RETIRE()

        client.delete_deployment.assert_not_awaited()
        client.delete_deployment_schedule.assert_not_awaited()

    async def test_a_failure_is_logged_and_the_worker_still_starts(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        name = prefect_app.RETIRED_DEPLOYMENTS[0]
        client = self._client(monkeypatch, {name: RuntimeError("database is locked")})

        await _RETIRE()

        assert "retiring_deployment_failed" in caplog.text
        client.delete_deployment.assert_not_awaited()
