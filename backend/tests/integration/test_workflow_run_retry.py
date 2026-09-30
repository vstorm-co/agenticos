"""Retrying a run from where it stopped, and filtering a run history."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.exceptions import AuthorizationError
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import WorkflowRunMode, WorkflowRunStatus, WorkflowRunTrigger
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_run import WorkflowRunFilters
from app.services.workflow_execution import WorkflowExecutionService
from app.services.workflow_execution.exceptions import (
    WorkflowArchivedError,
    WorkflowGraphUnresolvableError,
    WorkflowNotRunnableError,
    WorkflowRunNotRetryableError,
)
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import SeededRun, drive, node_statuses, seed_run

pytestmark = pytest.mark.anyio


class _Out(BaseModel):
    step: str


calls: Counter[str] = Counter()


@pytest.fixture(autouse=True)
def _no_prefect_submission() -> Iterator[None]:
    with patch("app.worker.tasks.workflow_tasks.run_deployment", new=AsyncMock()):
        yield


@pytest.fixture
def kinds() -> Iterator[tuple[str, str]]:
    """A step that always succeeds, and one that fails the first time it runs."""
    calls.clear()

    async def steady(config: object, node_input: object) -> NodeResult:
        calls["steady"] += 1
        return Completed[_Out](output=_Out(step=f"steady-{calls['steady']}"))

    async def flaky(config: object, node_input: object) -> NodeResult:
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            return Failed(error=WorkflowError(code="FLAKY", message="Not this time"))
        return Completed[_Out](output=_Out(step="flaky"))

    ids = []
    for name, handler in (("steady", steady), ("flaky", flaky)):
        node_id = f"test.retry-{name}-{uuid.uuid4().hex[:6]}"
        register(
            NodeDefinition(
                id=node_id,
                version=1,
                name=name,
                category="test",
                description="Registered only for retry tests.",
                kind="action",
                config_schema=None,
                input_schema=None,
                output_schema=_Out,
                ports=(
                    Port(id="in", label="In", kind="input", schema=None),
                    Port(id="out", label="Out", kind="output", schema=_Out),
                ),
                effect_kind="write",
                retry_guarantee="none",
                handler=handler,
            )
        )
        ids.append(node_id)
    yield ids[0], ids[1]
    for node_id in ids:
        REGISTRY.pop(node_id, None)


def _line(steady: str, flaky: str) -> tuple[WorkflowGraph, list[NodeInstance]]:
    nodes = [
        NodeInstance(
            id=uuid.uuid4(),
            definition_id=definition_id,
            definition_version=1,
            layout=NodePosition(x=0, y=0),
        )
        for definition_id in (steady, flaky, steady)
    ]
    edges = tuple(
        Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port="out",
            target_node_id=target.id,
            target_port="in",
        )
        for source, target in pairwise(nodes)
    )
    return WorkflowGraph(entry_node_id=nodes[0].id, nodes=tuple(nodes), edges=edges), nodes


async def _failed_run(engine: AsyncEngine, kinds: tuple[str, str]) -> tuple[SeededRun, list]:
    graph, nodes = _line(*kinds)
    seeded = await seed_run(engine, graph)
    run = await drive(seeded)
    assert run.status == WorkflowRunStatus.FAILED.value
    return seeded, nodes


class TestRetryingARun:
    async def test_it_runs_the_failed_step_and_what_it_missed_and_nothing_that_succeeded(
        self, engine: AsyncEngine, kinds
    ):
        seeded, nodes = await _failed_run(engine, kinds)
        assert calls == {"steady": 1, "flaky": 1}

        async with seeded.factory() as db:
            retried = await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)
            await db.commit()
            run = await workflow_run_repo.get_run(db, retried.id, organization_id=seeded.org.id)
        assert retried.retry_of_run_id == seeded.run.id
        again = SeededRun(
            run=run,
            graph=seeded.graph,
            principal=seeded.principal,
            org=seeded.org,
            factory=seeded.factory,
        )
        finished = await drive(again)

        assert finished.status == WorkflowRunStatus.SUCCEEDED.value
        # The first step's write is not made again; the failed step and the one
        # after it run.
        assert calls == {"steady": 2, "flaky": 2}
        statuses = await node_statuses(again)
        assert set(statuses.values()) == {"succeeded"}
        assert set(statuses) == {node.id for node in nodes}

    async def test_a_run_that_succeeded_is_not_retried(self, engine: AsyncEngine, kinds):
        steady, _flaky = kinds
        graph, _nodes = _line(steady, steady)
        seeded = await seed_run(engine, graph)
        await drive(seeded)

        async with seeded.factory() as db:
            with pytest.raises(WorkflowRunNotRetryableError):
                await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)

    @pytest.mark.security
    async def test_a_member_who_may_not_run_it_cannot_retry_it(self, engine: AsyncEngine, kinds):
        seeded, _nodes = await _failed_run(engine, kinds)

        async with seeded.factory() as db:
            for allowed in ([True, False], [True, True, False]):
                with (
                    patch(
                        "app.services.workflow_execution.facade.resolve_access",
                        new=AsyncMock(side_effect=allowed),
                    ),
                    pytest.raises(AuthorizationError),
                ):
                    # The second: a test run's retry also needs `workflows:edit`.
                    await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)

    async def test_an_archived_workflow_is_not_retried(self, engine: AsyncEngine, kinds):
        seeded, _nodes = await _failed_run(engine, kinds)
        async with seeded.factory() as db:
            workflow = await db.get(Workflow, seeded.run.workflow_id)
            assert workflow is not None
            workflow.status = WorkflowStatus.ARCHIVED.value
            await db.flush()

            with pytest.raises(WorkflowArchivedError):
                await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)

    async def test_a_run_whose_graph_no_longer_resolves_is_not_retried(
        self, engine: AsyncEngine, kinds
    ):
        seeded, _nodes = await _failed_run(engine, kinds)
        async with seeded.factory() as db:
            with (
                patch(
                    "app.services.workflow_execution.facade.dispatcher.resolve_graph",
                    new=AsyncMock(side_effect=WorkflowGraphUnresolvableError(run_id=seeded.run.id)),
                ),
                pytest.raises(WorkflowNotRunnableError),
            ):
                await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)


class TestFilteringRuns:
    async def test_runs_are_narrowed_by_state_mode_trigger_and_time(
        self, engine: AsyncEngine, kinds
    ):
        seeded, _nodes = await _failed_run(engine, kinds)
        service_filters = {
            "failed": WorkflowRunFilters(statuses=(WorkflowRunStatus.FAILED,)),
            "succeeded": WorkflowRunFilters(statuses=(WorkflowRunStatus.SUCCEEDED,)),
            "test": WorkflowRunFilters(mode=WorkflowRunMode.TEST),
            "real": WorkflowRunFilters(mode=WorkflowRunMode.REAL),
            "api": WorkflowRunFilters(triggered_by=WorkflowRunTrigger.API),
            "chat": WorkflowRunFilters(triggered_by=WorkflowRunTrigger.CHAT),
            "recent": WorkflowRunFilters(created_after=datetime.now(UTC) - timedelta(hours=1)),
            "future": WorkflowRunFilters(created_after=datetime.now(UTC) + timedelta(hours=1)),
            "before": WorkflowRunFilters(created_before=datetime.now(UTC) - timedelta(hours=1)),
        }
        async with seeded.factory() as db:
            service = WorkflowExecutionService(db)
            found = {
                name: (
                    await service.list(
                        seeded.ctx, workflow_id=seeded.run.workflow_id, filters=filters
                    )
                ).total
                for name, filters in service_filters.items()
            }

        assert found == {
            "failed": 1,
            "succeeded": 0,
            "test": 1,
            "real": 0,
            "api": 1,
            "chat": 0,
            "recent": 1,
            "future": 0,
            "before": 0,
        }
