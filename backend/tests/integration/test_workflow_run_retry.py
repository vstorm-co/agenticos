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
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import AuthorizationError
from app.db.models.artifact import Artifact
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
from app.workflows.contracts.io import Binding, LiteralValue
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import (
    SeededRun,
    drive,
    node_statuses,
    run_people,
    seed_agent,
    seed_member,
    seed_run,
)

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


def _line(
    steady: str, flaky: str, *, agent: dict[str, str] | None = None
) -> tuple[WorkflowGraph, list[NodeInstance]]:
    """`steady`, `flaky`, then `steady` again - or, given `agent`, a step asking it."""
    nodes = [
        NodeInstance(
            id=uuid.uuid4(),
            definition_id=definition_id,
            definition_version=1,
            layout=NodePosition(x=0, y=0),
        )
        for definition_id in (steady, flaky, steady)
    ]
    bindings: tuple[Binding, ...] = ()
    if agent is not None:
        nodes[2] = NodeInstance(
            id=uuid.uuid4(),
            definition_id="agent.run",
            definition_version=1,
            config={"agent": agent},
            layout=NodePosition(x=0, y=0),
        )
        bindings = (
            Binding(
                target_node_id=nodes[2].id, target_field="prompt", source=LiteralValue(value="Hi")
            ),
        )
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
    graph = WorkflowGraph(
        entry_node_id=nodes[0].id, nodes=tuple(nodes), edges=edges, bindings=bindings
    )
    return graph, nodes


async def _failed_run(
    engine: AsyncEngine, kinds: tuple[str, str], *, triggered_by: str = "api"
) -> tuple[SeededRun, list]:
    graph, nodes = _line(*kinds)
    seeded = await seed_run(engine, graph, triggered_by=triggered_by)
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


class TestRetryingAPublicRun:
    """A retry keeps its run's public origin: retried by a member from the
    console, a run in a chain an outsider started still has no person
    (D18a(5), owner decision 4). The retrier's role decides only whether they
    may retry it."""

    @pytest.mark.security
    async def test_a_retry_of_a_public_child_stays_public(self, engine: AsyncEngine, kinds):
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            member = await seed_member(db)
            await db.commit()
        steady, flaky = kinds
        graph, _nodes = _line(steady, flaky, agent=await seed_agent(factory, *member))
        root = await seed_run(
            engine, _line(steady, steady)[0], triggered_by="webhook", member=member
        )
        child = await seed_run(engine, graph, triggered_by="workflow_call", member=member)
        async with factory() as db:
            # Where a `workflow.run` step under the webhook run leaves its call.
            await workflow_run_repo.update_run(
                db,
                run=child.run,
                update_data={
                    "root_run_id": root.run.id,
                    "causation_run_id": root.run.id,
                    "depth": 1,
                    "public_origin": True,
                },
            )
            await db.commit()
        assert (await drive(child)).status == WorkflowRunStatus.FAILED.value

        async with factory() as db:
            retried = await WorkflowExecutionService(db).retry(child.ctx, child.run.id)
            await db.commit()
            run = await workflow_run_repo.get_run(db, retried.id, organization_id=child.org.id)
        assert run is not None
        assert (run.triggered_by, run.public_origin) == ("workflow_call", True)
        with run_people() as people:
            finished = await drive(
                SeededRun(
                    run=run, graph=graph, principal=child.principal, org=child.org, factory=factory
                )
            )
        assert finished.status == WorkflowRunStatus.SUCCEEDED.value, finished.error
        assert people == [None]

    @pytest.mark.security
    async def test_a_retry_of_a_public_root_stays_public(self, engine: AsyncEngine, kinds):
        seeded, _nodes = await _failed_run(engine, kinds, triggered_by="webhook")

        async with seeded.factory() as db:
            retried = await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)
            await db.commit()
            run = await workflow_run_repo.get_run(db, retried.id, organization_id=seeded.org.id)

        assert run is not None
        assert run.public_origin is True

    @pytest.mark.security
    async def test_a_retry_of_an_impersonated_run_stays_impersonated(
        self, engine: AsyncEngine, kinds
    ):
        seeded, _nodes = await _failed_run(engine, kinds)
        async with seeded.factory() as db:
            await workflow_run_repo.update_run(
                db, run=seeded.run, update_data={"impersonated": True}
            )
            await db.commit()

        async with seeded.factory() as db:
            retried = await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)
            await db.commit()
            run = await workflow_run_repo.get_run(db, retried.id, organization_id=seeded.org.id)

        assert run is not None
        assert run.impersonated is True

    async def test_a_retry_of_a_member_run_is_not_public(self, engine: AsyncEngine, kinds):
        seeded, _nodes = await _failed_run(engine, kinds)

        async with seeded.factory() as db:
            retried = await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)
            await db.commit()
            run = await workflow_run_repo.get_run(db, retried.id, organization_id=seeded.org.id)

        assert run is not None
        assert run.public_origin is False

    async def test_a_retry_of_an_app_run_names_the_same_page_and_version(
        self, engine: AsyncEngine, kinds
    ):
        seeded, _nodes = await _failed_run(engine, kinds, triggered_by="app")
        async with seeded.factory() as db:
            page = Artifact(
                organization_id=seeded.org.id,
                owner_user_id=seeded.principal.id,
                name="tool",
                title="Tool",
                visibility="private",
            )
            db.add(page)
            await db.flush()
            await workflow_run_repo.update_run(
                db,
                run=await workflow_run_repo.get_run(
                    db, seeded.run.id, organization_id=seeded.org.id
                ),
                update_data={"source_artifact_id": page.id, "source_version_number": 4},
            )
            await db.commit()
            page_id = page.id

        async with seeded.factory() as db:
            retried = await WorkflowExecutionService(db).retry(seeded.ctx, seeded.run.id)
            await db.commit()
            run = await workflow_run_repo.get_run(db, retried.id, organization_id=seeded.org.id)

        assert run is not None
        assert (run.triggered_by, run.source_artifact_id, run.source_version_number) == (
            "app",
            page_id,
            4,
        )


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
