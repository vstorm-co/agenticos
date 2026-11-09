"""Health admission excludes parked, unrelated, revoked and obsolete work."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.watch import Watch, WatchAttemptStatus
from app.services import routine_health as health

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)


def trigger() -> AgentTrigger:
    return AgentTrigger(
        id=uuid4(),
        organization_id=uuid4(),
        created_by_user_id=uuid4(),
        is_active=True,
        max_failures=3,
        consecutive_failures=0,
    )


def run(parent: AgentTrigger, *, watch: bool = False) -> AgentRun:
    return AgentRun(
        id=uuid4(),
        organization_id=parent.organization_id,
        user_id=parent.created_by_user_id,
        routine_origin_id=parent.id,
        routine_kind="watch" if watch else "trigger",
        status=RunStatus.FAILED.value,
        started_at=NOW,
    )


@pytest.mark.parametrize("excluded", ["delegate", "no_origin", "parked", "no_clock", "other_kind"])
async def test_unrelated_or_nonterminal_runs_do_not_query_a_parent(
    monkeypatch: pytest.MonkeyPatch, excluded: str
) -> None:
    current = run(trigger())
    if excluded == "delegate":
        current.parent_run_id = uuid4()
    elif excluded == "no_origin":
        current.routine_origin_id = None
    elif excluded == "parked":
        current.status = RunStatus.AWAITING_ANSWER.value
    elif excluded == "no_clock":
        current.started_at = None
    else:
        current.routine_kind = "not-a-routine"
    lookup = AsyncMock()
    monkeypatch.setattr(health.trigger_repo, "get_by_id", lookup)
    await health.RoutineHealthService(AsyncMock(spec=AsyncSession)).run_result(current)
    lookup.assert_not_awaited()


@pytest.mark.parametrize("kind", ["trigger", "watch"])
@pytest.mark.parametrize("refusal", ["missing", "organization", "owner"])
async def test_parent_must_belong_to_the_same_run_owner_and_organization(
    monkeypatch: pytest.MonkeyPatch, kind: str, refusal: str
) -> None:
    parent = trigger()
    current = run(parent, watch=kind == "watch")
    found = (
        parent
        if kind == "trigger"
        else Watch(
            id=parent.id, organization_id=parent.organization_id, user_id=parent.created_by_user_id
        )
    )
    if refusal == "organization":
        current.organization_id = uuid4()
    elif refusal == "owner":
        current.user_id = uuid4()
    lookup = AsyncMock(return_value=None if refusal == "missing" else found)
    monkeypatch.setattr(
        health.trigger_repo if kind == "trigger" else health.watch_repo, "get_by_id", lookup
    )
    observe = AsyncMock()
    monkeypatch.setattr(health.health_repo, "observe", observe)
    await health.RoutineHealthService(AsyncMock(spec=AsyncSession)).run_result(current)
    observe.assert_not_awaited()


@pytest.mark.parametrize("state", ["paused", "disabled", "ended", "old", "owner_gone"])
async def test_paused_disabled_ended_and_previous_window_results_do_not_change_health(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    parent = trigger()
    current = run(parent)
    if state == "paused":
        parent.is_active = False
    elif state == "disabled":
        parent.max_failures = None
    elif state == "ended":
        parent.ends_at = NOW - timedelta(seconds=1)
    elif state == "old":
        parent.health_reset_at = NOW + timedelta(seconds=1)
    else:
        parent.created_by_user_id = None
    monkeypatch.setattr(health.trigger_repo, "get_by_id", AsyncMock(return_value=parent))
    observe = AsyncMock()
    monkeypatch.setattr(health.health_repo, "observe", observe)
    service = health.RoutineHealthService(AsyncMock(spec=AsyncSession))
    if state == "owner_gone":
        await service._record(parent, at=NOW, healthy=False)
    else:
        await service.run_result(current)
    observe.assert_not_awaited()


@pytest.mark.parametrize("refusal", ["missing", "organization", "owner"])
async def test_watch_source_observations_recheck_the_current_parent(
    monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    original = Watch(id=uuid4(), organization_id=uuid4(), user_id=uuid4())
    current = Watch(
        id=original.id, organization_id=original.organization_id, user_id=original.user_id
    )
    if refusal == "organization":
        current.organization_id = uuid4()
    elif refusal == "owner":
        current.user_id = uuid4()
    monkeypatch.setattr(
        health.watch_repo,
        "get_by_id",
        AsyncMock(return_value=None if refusal == "missing" else current),
    )
    observe = AsyncMock()
    monkeypatch.setattr(health.health_repo, "observe", observe)
    await health.RoutineHealthService(AsyncMock(spec=AsyncSession)).watch_result(
        original, at=NOW, status=WatchAttemptStatus.SOURCE_UNAVAILABLE
    )
    observe.assert_not_awaited()
