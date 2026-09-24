"""What a dispatch tick does to a run, against a real Postgres.

Each test drives `claim` / `begin_attempt` / `call_handler` / `settle` the way
`workflow_dispatch_node_flow` sequences them, one committed transaction per
phase, with a node definition registered for the test so the handler can do
what no shipped node does yet: spend money, raise, wait.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.db.models.workflow import Workflow, WorkflowStatus
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeRun,
    NodeRunStatus,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as workflow_run_repo
from app.services.workflow_execution import context, dispatcher
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, Port
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph

pytestmark = pytest.mark.anyio

Handler = Callable[[object, object], Awaitable[NodeResult]]


class _Config(BaseModel):
    message: str = ""


class _Output(BaseModel):
    echoed: str


@dataclass
class Seeded:
    run: WorkflowRun
    entry: NodeRun
    graph: WorkflowGraph
    principal: User
    org: Organization
    factory: async_sessionmaker[AsyncSession]


@pytest.fixture
def node_kind() -> Iterator[Callable[..., str]]:
    """Registers a node definition whose handler the test supplies, and removes
    every one it registered afterwards."""
    registered: list[str] = []

    def _register(handler: Handler, *, retry_guarantee: str = "idempotent") -> str:
        node_id = f"test.dispatch-{uuid.uuid4().hex[:8]}"
        register(
            NodeDefinition(
                id=node_id,
                version=1,
                name="Test node",
                category="test",
                description="Registered only for dispatch integration tests.",
                kind="action",
                config_schema=_Config,
                input_schema=_Config,
                output_schema=_Output,
                ports=(
                    Port(id="in", label="In", kind="input", schema=_Config),
                    Port(id="out", label="Out", kind="output", schema=_Output),
                ),
                effect_kind="pure",
                retry_guarantee=retry_guarantee,
                handler=handler,
            )
        )
        registered.append(node_id)
        return node_id

    yield _register
    for node_id in registered:
        REGISTRY.pop(node_id, None)


def _chain(node_id: str, length: int) -> WorkflowGraph:
    nodes = tuple(
        NodeInstance(
            id=uuid.uuid4(),
            definition_id=node_id,
            definition_version=1,
            config={"message": "hi"},
            layout=NodePosition(x=index * 100, y=0),
        )
        for index in range(length)
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
    return WorkflowGraph(entry_node_id=nodes[0].id, nodes=nodes, edges=edges)


async def _seed(
    engine: AsyncEngine,
    graph: WorkflowGraph,
    *,
    budget_limit: Decimal | None = None,
    role: str = "owner",
) -> Seeded:
    """A `running` test-mode run of `graph`, started by an active member holding
    `role`, with the entry node's outbox row ready to claim - what
    `WorkflowExecutionService.start` leaves behind."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        principal = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(principal)
        await db.flush()
        org = Organization(
            id=uuid.uuid4(),
            name="Acme",
            slug=f"acme-{uuid.uuid4().hex[:8]}",
            created_by_user_id=principal.id,
        )
        db.add(org)
        await db.flush()
        db.add(
            OrganizationMember(
                id=uuid.uuid4(), organization_id=org.id, user_id=principal.id, role=role
            )
        )
        workflow = Workflow(
            id=uuid.uuid4(),
            organization_id=org.id,
            owner_user_id=principal.id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name="Chain",
            status=WorkflowStatus.PUBLISHED.value,
            visibility=Visibility.PRIVATE.value,
            draft_graph=graph.model_dump(mode="json"),
        )
        db.add(workflow)
        await db.flush()
        run = await workflow_run_repo.create_run(
            db,
            organization_id=org.id,
            workflow_id=workflow.id,
            workflow_version_id=None,
            draft_graph_snapshot=graph.model_dump(mode="json"),
            mode=WorkflowRunMode.TEST.value,
            triggered_by="api",
            execution_principal_user_id=principal.id,
            budget_limit=budget_limit,
            deadline_at=None,
            root_run_id=None,
            causation_run_id=None,
            visited_trigger_ids=[],
            depth=0,
            started_at=datetime.now(UTC),
        )
        entry = await workflow_run_repo.create_node_run(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_instance_id=graph.entry_node_id,
            scope_path=[],
        )
        await workflow_run_repo.create_outbox(
            db,
            organization_id=org.id,
            workflow_run_id=run.id,
            node_run_id=entry.id,
            available_at=datetime.now(UTC),
        )
        run = await workflow_run_repo.update_run(
            db, run=run, update_data={"status": WorkflowRunStatus.RUNNING.value}
        )
        await db.commit()
    return Seeded(run=run, entry=entry, graph=graph, principal=principal, org=org, factory=factory)


async def _tick(seeded: Seeded, node_run_id: uuid.UUID) -> dispatcher.BegunAttempt | None:
    """One `workflow_dispatch_node_flow` tick for `node_run_id`, phase by phase."""
    factory = seeded.factory
    async with factory() as db:
        claim = await dispatcher.claim(db, node_run_id=node_run_id)
        await db.commit()
    assert claim is not None and claim.claimed_by is not None
    async with factory() as db:
        begun = await dispatcher.begin_attempt(
            db, workflow_run_id=seeded.run.id, node_run_id=node_run_id, token=claim.claimed_by
        )
        await db.commit()
    if begun is None:
        return None
    outcome = await dispatcher.call_handler(begun)
    async with factory() as db:
        await dispatcher.settle(db, begun=begun, outcome=outcome)
        await db.commit()
    return begun


async def _run_row(seeded: Seeded) -> WorkflowRun:
    async with seeded.factory() as db:
        return (
            await db.execute(select(WorkflowRun).where(WorkflowRun.id == seeded.run.id))
        ).scalar_one()


async def _node_runs(seeded: Seeded) -> list[NodeRun]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(NodeRun)
                    .where(NodeRun.workflow_run_id == seeded.run.id)
                    .order_by(NodeRun.created_at)
                )
            ).scalars()
        )


async def _outbox_rows(seeded: Seeded) -> list[DispatchOutbox]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(DispatchOutbox).where(DispatchOutbox.workflow_run_id == seeded.run.id)
                )
            ).scalars()
        )


async def _attempt_costs(seeded: Seeded) -> list[Decimal]:
    async with seeded.factory() as db:
        rows = (
            await db.execute(
                select(NodeAttempt)
                .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
                .where(NodeRun.workflow_run_id == seeded.run.id)
                .order_by(NodeAttempt.created_at)
            )
        ).scalars()
        return [row.cost for row in rows]


async def _spend(amount: str) -> NodeResult:
    context.report_cost(Decimal(amount))
    return Completed[_Output](output=_Output(echoed="spent"))


class TestCostAndBudget:
    async def test_what_a_node_reports_spending_lands_on_its_attempt_and_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        async def handler(_config: object, _input: object) -> NodeResult:
            return await _spend("0.015")

        seeded = await _seed(engine, _chain(node_kind(handler), 1))

        await _tick(seeded, seeded.entry.id)

        run = await _run_row(seeded)
        assert run.spent_cost == Decimal("0.015")
        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        assert await _attempt_costs(seeded) == [Decimal("0.015")]

    @pytest.mark.security
    async def test_a_spent_budget_refuses_the_next_node_and_ends_the_run(
        self, engine: AsyncEngine, node_kind
    ):
        """The first node's spend reaches the cap, so the second is refused
        before its handler runs - and the refusal ends the run in every column
        a reader checks, rather than parking it with a pending node."""
        calls: list[str] = []

        async def handler(_config: object, _input: object) -> NodeResult:
            calls.append("called")
            return await _spend("0.02")

        seeded = await _seed(engine, _chain(node_kind(handler), 2), budget_limit=Decimal("0.02"))

        await _tick(seeded, seeded.entry.id)
        second = (await _node_runs(seeded))[1]
        assert await _tick(seeded, second.id) is None

        assert calls == ["called"]
        run = await _run_row(seeded)
        assert run.status == WorkflowRunStatus.BUDGET_EXCEEDED.value
        assert run.ended_at is not None
        assert run.error is not None and run.error["code"] == "BUDGET_EXCEEDED"
        assert run.spent_cost == Decimal("0.02")
        assert [node.status for node in await _node_runs(seeded)] == [
            NodeRunStatus.SUCCEEDED.value,
            NodeRunStatus.CANCELLED.value,
        ]
        assert {row.status for row in await _outbox_rows(seeded)} == {
            DispatchOutboxStatus.DONE.value
        }
