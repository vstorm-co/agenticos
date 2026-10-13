"""The scheduled usage reports, and which agents they reach.

The flow itself is a loop, and a loop over an estate is exactly where a report
goes quietly wrong: one unreadable spec stopping every later agent, a draft's
unpublished settings deciding who gets mailed, an agent with no version at all
raising inside a weekly job nobody watches. Those are what these pin.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.spec import AgentSpec, AlertSpec, NotificationSpec
from app.worker.tasks.report_tasks import _run_agent_reports, _run_reports

MODULE = "app.worker.tasks.report_tasks"

_WINDOW_START = datetime.now(UTC)


def _agent(*, version_id=None, org_id=None):
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.organization_id = org_id or uuid.uuid4()
    agent.current_version_id = version_id
    return agent


def _version(spec: AgentSpec):
    version = MagicMock()
    version.spec = spec.model_dump(mode="json")
    return version


def _asking_spec() -> AgentSpec:
    return AgentSpec(name="Reported", notifications=NotificationSpec(usage=AlertSpec(enabled=True)))


@pytest.mark.anyio
async def test_the_published_version_decides_who_is_mailed_not_the_draft():
    """Who hears about an agent is part of its spec, so it is published like
    everything else there. An unsaved edit to the audience must not change who
    gets mailed on Monday."""
    agent = _agent(version_id=uuid.uuid4())
    notifications = MagicMock(agent_usage_report=AsyncMock(return_value=True))

    with (
        patch(f"{MODULE}.agent_repo.list_all_published", new=AsyncMock(return_value=[agent])),
        patch(
            f"{MODULE}.agent_repo.get_version",
            new=AsyncMock(return_value=_version(_asking_spec())),
        ) as get_version,
    ):
        reported = await _run_agent_reports(MagicMock(), notifications, "weekly", _WINDOW_START)

    assert reported == 1
    # The version the agent currently points at, scoped to its own tenant.
    assert get_version.await_args.args[1] == agent.current_version_id
    assert get_version.await_args.kwargs["organization_id"] == agent.organization_id


@pytest.mark.anyio
async def test_an_agent_that_was_never_published_is_skipped_not_crashed_on():
    """`list_all_published` filters on status, but a row can carry the published
    status with no `current_version_id` - and reading a version by `None` is a
    query nobody should be issuing."""
    notifications = MagicMock(agent_usage_report=AsyncMock(return_value=True))

    with (
        patch(
            f"{MODULE}.agent_repo.list_all_published",
            new=AsyncMock(return_value=[_agent(version_id=None)]),
        ),
        patch(f"{MODULE}.agent_repo.get_version", new=AsyncMock()) as get_version,
    ):
        reported = await _run_agent_reports(MagicMock(), notifications, "weekly", _WINDOW_START)

    assert reported == 0
    get_version.assert_not_awaited()


@pytest.mark.anyio
async def test_a_version_that_has_gone_missing_is_skipped():
    notifications = MagicMock(agent_usage_report=AsyncMock(return_value=True))

    with (
        patch(
            f"{MODULE}.agent_repo.list_all_published",
            new=AsyncMock(return_value=[_agent(version_id=uuid.uuid4())]),
        ),
        patch(f"{MODULE}.agent_repo.get_version", new=AsyncMock(return_value=None)),
    ):
        reported = await _run_agent_reports(MagicMock(), notifications, "weekly", _WINDOW_START)

    assert reported == 0
    notifications.agent_usage_report.assert_not_awaited()


@pytest.mark.anyio
async def test_one_unreadable_spec_does_not_stop_the_rest_of_the_estate():
    """The real possibility here: a spec written by an older version of this code
    that no longer validates. Without the guard, every agent after it in the loop
    silently stops being reported on."""
    broken, working = _agent(version_id=uuid.uuid4()), _agent(version_id=uuid.uuid4())
    unreadable = MagicMock()
    unreadable.spec = {"name": "Broken", "not_a_field": True}
    notifications = MagicMock(agent_usage_report=AsyncMock(return_value=True))

    async def version_for(_db, version_id, *, organization_id):
        return unreadable if version_id == broken.current_version_id else _version(_asking_spec())

    with (
        patch(
            f"{MODULE}.agent_repo.list_all_published",
            new=AsyncMock(return_value=[broken, working]),
        ),
        patch(f"{MODULE}.agent_repo.get_version", new=AsyncMock(side_effect=version_for)),
    ):
        reported = await _run_agent_reports(MagicMock(), notifications, "weekly", _WINDOW_START)

    assert reported == 1


@pytest.mark.anyio
async def test_a_mail_failure_for_one_agent_does_not_stop_the_next():
    first, second = _agent(version_id=uuid.uuid4()), _agent(version_id=uuid.uuid4())
    notifications = MagicMock(
        agent_usage_report=AsyncMock(side_effect=[RuntimeError("smtp down"), True])
    )

    with (
        patch(
            f"{MODULE}.agent_repo.list_all_published",
            new=AsyncMock(return_value=[first, second]),
        ),
        patch(
            f"{MODULE}.agent_repo.get_version",
            new=AsyncMock(return_value=_version(_asking_spec())),
        ),
    ):
        reported = await _run_agent_reports(MagicMock(), notifications, "weekly", _WINDOW_START)

    assert reported == 1


@pytest.mark.anyio
async def test_an_agent_whose_spec_declines_the_report_is_not_counted():
    """The service returns False for a disabled alert, and the count has to
    reflect what was actually sent rather than what was considered."""
    notifications = MagicMock(agent_usage_report=AsyncMock(return_value=False))

    with (
        patch(
            f"{MODULE}.agent_repo.list_all_published",
            new=AsyncMock(return_value=[_agent(version_id=uuid.uuid4())]),
        ),
        patch(
            f"{MODULE}.agent_repo.get_version",
            new=AsyncMock(return_value=_version(AgentSpec(name="Quiet"))),
        ),
    ):
        reported = await _run_agent_reports(MagicMock(), notifications, "weekly", _WINDOW_START)

    assert reported == 0


class TestWindowStartIsIdempotentAcrossRetries:
    """The dedup key a retried report is caught on is `(subject, period,
    window_start)` - so two invocations that both fire today, whether a
    genuine Prefect retry or an accidental second trigger, must compute the
    identical `window_start` or the constraint has nothing to catch
    (`.claude/skills/background-task/SKILL.md`'s idempotency rule)."""

    @asynccontextmanager
    async def _fake_db_context(self):
        yield MagicMock()

    async def _captured_window_starts(self) -> list[datetime]:
        captured: list[datetime] = []

        class _Notifications:
            def __init__(self, db):
                pass

            async def usage_report(self, organization_id, *, period, window_start):
                captured.append(window_start)
                return False

        with (
            patch(f"{MODULE}.get_db_context", self._fake_db_context),
            patch(
                f"{MODULE}.organization_repo.list_all",
                new=AsyncMock(return_value=[MagicMock(id=uuid.uuid4())]),
            ),
            patch(f"{MODULE}.agent_repo.list_all_published", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.NotificationService", new=_Notifications),
        ):
            await _run_reports("weekly")
        return captured

    @pytest.mark.anyio
    async def test_the_window_start_is_rounded_to_midnight_utc(self):
        captured = await self._captured_window_starts()
        window_start = captured[0]
        assert (window_start.hour, window_start.minute, window_start.second) == (0, 0, 0)
        assert window_start.microsecond == 0

    @pytest.mark.anyio
    async def test_two_calls_the_same_day_compute_the_same_window(self):
        first = await self._captured_window_starts()
        second = await self._captured_window_starts()
        assert first[0] == second[0]

    @pytest.mark.anyio
    async def test_a_real_flow_runs_scheduled_time_wins_over_the_midnight_it_straddles(self):
        """Rounding alone survives a retry landing a few seconds later, not
        one whose wall clock crosses midnight between attempts. Two
        attempts of the *same scheduled run* share one `expected_start_time`
        regardless of when either actually executes - reading it, when a
        real flow run provides one, is what closes that gap."""
        expected_start_time = datetime(2026, 3, 4, 23, 59, 59, tzinfo=UTC)
        flow_run_context = MagicMock()
        flow_run_context.flow_run.expected_start_time = expected_start_time

        with patch(f"{MODULE}.FlowRunContext.get", return_value=flow_run_context):
            captured = await self._captured_window_starts()

        assert captured[0] == datetime(2026, 3, 4, tzinfo=UTC)
