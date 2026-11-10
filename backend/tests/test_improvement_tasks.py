"""Worker transitions announce only committed changes and propagate failures."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.schemas.change_event import ChangeEvent
from app.worker.jobs import AdvanceImprovement
from app.worker.tasks import improvement_tasks

pytestmark = pytest.mark.anyio


@dataclass
class State:
    agent_id: UUID
    status: str = "running"
    stage: str = "preparing"
    iteration: int = 1


@pytest.mark.parametrize("change", ["status", "stage", "iteration", "none", "missing"])
async def test_only_a_committed_transition_emits_an_agent_update(change: str) -> None:
    job = AdvanceImprovement(run_id=uuid4(), organization_id=uuid4())
    row = State(agent_id=uuid4()) if change != "missing" else None
    events: list[str] = []
    db = MagicMock()

    @asynccontextmanager
    async def session() -> AsyncGenerator[MagicMock]:
        events.append("begin")
        yield db
        events.append("commit")

    async def advance(run_id: UUID, organization_id: UUID) -> None:
        assert (run_id, organization_id) == (job.run_id, job.organization_id)
        if row is not None:
            if change == "status":
                row.status = "stopped"
            elif change == "stage":
                row.stage = "proposing"
            elif change == "iteration":
                row.iteration = 2

    async def publish(event: ChangeEvent) -> None:
        assert events == ["begin", "commit"]
        assert row is not None
        assert (event.organization_id, event.resource, event.id) == (
            job.organization_id,
            "agent",
            row.agent_id,
        )
        assert event.action == "updated" and event.surface == "system"
        assert event.actor_user_id is None
        events.append("published")

    with (
        patch.object(improvement_tasks, "get_worker_db_context", session),
        patch("app.repositories.improvement_repo.get_run", AsyncMock(return_value=row)),
        patch(
            "app.services.improvement_pipeline.ImprovementPipelineService",
            return_value=MagicMock(advance=advance),
        ),
        patch("app.services.change_feed.connect_in_worker", AsyncMock()),
        patch("app.services.change_feed.publish", publish),
    ):
        await improvement_tasks.advance_improvement(job)
    assert events == (
        ["begin", "commit", "published"]
        if change not in {"none", "missing"}
        else ["begin", "commit"]
    )


async def test_a_failed_transition_rolls_back_without_announcing_success() -> None:
    db = MagicMock()
    events: list[str] = []

    @asynccontextmanager
    async def session() -> AsyncGenerator[MagicMock]:
        try:
            yield db
        except RuntimeError:
            events.append("rollback")
            raise

    with (
        patch.object(improvement_tasks, "get_worker_db_context", session),
        patch("app.repositories.improvement_repo.get_run", AsyncMock(return_value=State(uuid4()))),
        patch(
            "app.services.improvement_pipeline.ImprovementPipelineService",
            return_value=MagicMock(advance=AsyncMock(side_effect=RuntimeError("database failed"))),
        ),
        patch("app.services.change_feed.connect_in_worker", AsyncMock()),
        patch("app.services.change_feed.publish", AsyncMock()) as publish,
        pytest.raises(RuntimeError, match="database failed"),
    ):
        await improvement_tasks.advance_improvement(
            AdvanceImprovement(run_id=uuid4(), organization_id=uuid4())
        )
    assert events == ["rollback"]
    publish.assert_not_awaited()


async def test_the_recovery_tick_returns_the_count_after_committing() -> None:
    events: list[str] = []
    db = MagicMock()

    @asynccontextmanager
    async def session() -> AsyncGenerator[MagicMock]:
        yield db
        events.append("commit")

    with (
        patch.object(improvement_tasks, "get_worker_db_context", session),
        patch(
            "app.services.improvement_pipeline.ImprovementPipelineService",
            return_value=MagicMock(sweep=AsyncMock(return_value=3)),
        ),
    ):
        assert await improvement_tasks.sweep_improvements() == 3
    assert events == ["commit"]


@dataclass
class SkillState:
    skill_id: UUID
    status: str = "running"
    stage: str = "understanding"
    iteration: int = 1


async def test_a_skill_session_step_and_its_sweep_run_in_one_worker_transaction() -> None:
    from app.worker.jobs import AdvanceSkillImprovement

    job = AdvanceSkillImprovement(run_id=uuid4(), organization_id=uuid4())
    events: list[str] = []
    service = MagicMock(advance=AsyncMock(), sweep=AsyncMock(return_value=3))

    @asynccontextmanager
    async def session() -> AsyncGenerator[MagicMock]:
        events.append("begin")
        yield MagicMock()
        events.append("commit")

    with (
        patch.object(improvement_tasks, "get_worker_db_context", session),
        patch("app.repositories.skill_improvement_repo.get_run", AsyncMock(return_value=None)),
        patch("app.services.skill_improvement.SkillImprovementService", return_value=service),
        patch("app.services.change_feed.connect_in_worker", AsyncMock()),
        patch("app.services.change_feed.publish", AsyncMock()) as publish,
    ):
        await improvement_tasks.advance_skill_improvement(job)
        swept = await improvement_tasks.sweep_skill_improvements()

    service.advance.assert_awaited_once_with(job.run_id, job.organization_id)
    assert swept == 3 and events == ["begin", "commit", "begin", "commit"]
    publish.assert_not_awaited()


@pytest.mark.parametrize("change", ["status", "stage", "iteration", "none"])
async def test_a_skill_session_step_announces_its_skill_once_committed(change: str) -> None:
    from app.worker.jobs import AdvanceSkillImprovement

    job = AdvanceSkillImprovement(run_id=uuid4(), organization_id=uuid4())
    row = SkillState(skill_id=uuid4())
    events: list[str] = []

    @asynccontextmanager
    async def session() -> AsyncGenerator[MagicMock]:
        events.append("begin")
        yield MagicMock()
        events.append("commit")

    async def advance(run_id: UUID, organization_id: UUID) -> None:
        if change == "status":
            row.status = "waiting"
        elif change == "stage":
            row.stage = "changes"
        elif change == "iteration":
            row.iteration = 2

    async def publish(event: ChangeEvent) -> None:
        assert events == ["begin", "commit"]
        assert (event.organization_id, event.resource, event.id) == (
            job.organization_id,
            "skill",
            row.skill_id,
        )
        assert event.action == "updated" and event.surface == "system"
        assert event.actor_user_id is None
        events.append("published")

    with (
        patch.object(improvement_tasks, "get_worker_db_context", session),
        patch("app.repositories.skill_improvement_repo.get_run", AsyncMock(return_value=row)),
        patch(
            "app.services.skill_improvement.SkillImprovementService",
            return_value=MagicMock(advance=advance),
        ),
        patch("app.services.change_feed.connect_in_worker", AsyncMock()),
        patch("app.services.change_feed.publish", publish),
    ):
        await improvement_tasks.advance_skill_improvement(job)
    assert events == (["begin", "commit"] if change == "none" else ["begin", "commit", "published"])
