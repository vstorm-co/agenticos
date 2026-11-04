"""Parallel branches end to end: forks, joins, failure, cancel, status (#1800 slice 2).

Every graph is driven through the real dispatcher against Postgres. What is proved is
what an author relies on: the legs of a fork run side by side and a step that joins them
waits for all, a Merge set to wait for all hands each branch on by name, a failing or
cancelled leg closes the work its siblings had under way, and the run's status reads the
most severe of its live steps.
"""

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.background_job import BackgroundJob
from app.db.models.workflow_approval import WorkflowApproval
from app.db.models.workflow_log_entry import WorkflowLogEntry
from app.db.models.workflow_run import (
    DispatchOutbox,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.services.workflow_execution import WorkflowExecutionService, cleanup, context, dispatcher
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, NodeHandler, Port, RetryGuarantee
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.contracts.policy import NodePolicy
from app.workflows.contracts.results import (
    Completed,
    Failed,
    NodeResult,
    Uncertain,
    Waiting,
    WorkflowError,
)
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, QuickLog, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import (
    SeededRun,
    begin,
    drive,
    node_statuses,
    queued_dispatches,
    run_row,
    seed_run,
    settle,
    start_attempt,
    tick,
)

pytestmark = pytest.mark.anyio


def _node(
    definition_id: str, config: dict[str, Any] | None = None, *, policy: NodePolicy | None = None
) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        policy=policy,
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance, port: str = "out") -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


def _bind(target: NodeInstance, field: str, source: NodeInstance, port: str, *path: str) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port=port, field_path=path),
    )


def _map(field: str, value: str) -> dict[str, Any]:
    return {"mappings": [{"target_field": field, "source_path": f"'{value}'"}]}


async def _run(engine: AsyncEngine, graph: WorkflowGraph, run_input: dict[str, Any] | None = None):
    """Seed a run of `graph` and publish-check it first."""
    seeded = await seed_run(engine, graph, run_input=run_input)
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    return seeded


async def _row_of(seeded: SeededRun, node: NodeInstance) -> NodeRun | None:
    async with seeded.factory() as db:
        return (
            await db.execute(
                select(NodeRun).where(
                    NodeRun.workflow_run_id == seeded.run.id,
                    NodeRun.node_instance_id == node.id,
                    NodeRun.scope_path == [],
                )
            )
        ).scalar_one_or_none()


async def _tick(seeded: SeededRun, node: NodeInstance) -> None:
    row = await _row_of(seeded, node)
    assert row is not None, "the step has no row to tick"
    await tick(seeded, row.id)


async def _live_outbox(seeded: SeededRun, node: NodeInstance) -> list[DispatchOutbox]:
    row = await _row_of(seeded, node)
    assert row is not None
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(DispatchOutbox).where(
                        DispatchOutbox.node_run_id == row.id,
                        DispatchOutbox.status.in_(["pending", "claimed"]),
                    )
                )
            )
            .scalars()
            .all()
        )


# Synthetic steps: one that fails, one that waits, one the test controls.


class _Empty(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Resumed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_run_id: uuid.UUID


_calls: list[str] = []
_parks_on: list[uuid.UUID] = []
_gate: dict[str, asyncio.Event] = {}


async def _fails(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    return Failed(error=WorkflowError(code="LEG_FAILED", message="This leg failed"))


async def _fails_again(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    return Failed(error=WorkflowError(code="SECOND_FAILED", message="The second leg failed too"))


async def _retries(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    return Failed(error=WorkflowError(code="TRANSIENT", message="Try again", retryable=True))


async def _unsure(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    return Uncertain(detail="Cannot tell whether the write landed")


async def _records(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """A side effect worth never repeating: it notes that it ran."""
    _calls.append(str(context.current().node_instance_id))
    return Completed[_Empty](output=_Empty())


async def _asks_approval(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    current = context.current()
    if current.resumed_agent_run_id is None:
        context.report_waiting_agent_run(_parks_on.pop(0))
        return Waiting(reason="approval", resume_token="t")
    return Completed[_Resumed](output=_Resumed(agent_run_id=current.resumed_agent_run_id))


def _synthetic(
    node_id: str,
    handler: NodeHandler,
    *,
    effect: Literal["pure", "read", "write"] = "pure",
    guarantee: RetryGuarantee = "idempotent",
) -> NodeDefinition:
    return NodeDefinition(
        id=node_id,
        version=1,
        name=node_id,
        category="test",
        description="A test node.",
        kind="action",
        config_schema=None,
        input_schema=None,
        output_schema=_Empty,
        ports=(
            Port(id="in", label="In", kind="input", schema=None),
            Port(id="out", label="Out", kind="output", schema=_Empty),
        ),
        effect_kind=effect,
        retry_guarantee=guarantee,
        handler=handler,
    )


@pytest.fixture
def synthetic_nodes() -> Iterator[None]:
    definitions = [
        _synthetic("test.fails", _fails),
        _synthetic("test.fails_again", _fails_again),
        _synthetic("test.retries", _retries),
        _synthetic("test.unsure", _unsure, effect="write", guarantee="none"),
        _synthetic("test.records", _records, effect="write", guarantee="at_least_once"),
        replace(
            _synthetic("test.asks_approval", _asks_approval, effect="write"),
            output_schema=_Resumed,
            ports=(
                Port(id="in", label="In", kind="input", schema=None),
                Port(id="out", label="Out", kind="output", schema=_Resumed),
            ),
        ),
    ]
    for definition in definitions:
        register(definition)
    _calls.clear()
    _parks_on.clear()
    yield
    for definition in definitions:
        REGISTRY.pop(definition.id, None)


# Forks and joins


class _Fork:
    """entry -> A, B -> join: two legs side by side, one step that needs both."""

    def __init__(self, join: str = "data.map", join_config: dict[str, Any] | None = None) -> None:
        self.entry = _node("core.input")
        self.a = _node("data.map", _map("a", "x"))
        self.b = _node("data.map", _map("b", "y"))
        self.join = _node(join, _map("c", "z") if join_config is None else join_config)
        self.graph = WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=(self.entry, self.a, self.b, self.join),
            edges=(
                _edge(self.entry, self.a),
                _edge(self.entry, self.b),
                _edge(self.a, self.join),
                _edge(self.b, self.join),
            ),
        )


async def test_a_fork_queues_every_leg_in_the_settle_that_ends_it(engine: AsyncEngine):
    fork = _Fork()
    seeded = await _run(engine, fork.graph)

    await _tick(seeded, fork.entry)

    legs = [await _row_of(seeded, fork.a), await _row_of(seeded, fork.b)]
    assert all(leg is not None for leg in legs)
    assert [(await _live_outbox(seeded, node))[0].status for node in (fork.a, fork.b)] == [
        "pending",
        "pending",
    ]
    queued = {job.payload["node_run_id"] for job in await queued_dispatches(seeded.factory)}
    assert queued == {str(leg.id) for leg in legs if leg is not None}


async def test_a_join_waits_for_every_parallel_leg(engine: AsyncEngine):
    fork = _Fork()
    seeded = await _run(engine, fork.graph)

    await _tick(seeded, fork.entry)
    await _tick(seeded, fork.a)
    assert fork.join.id not in await node_statuses(seeded)

    await _tick(seeded, fork.b)
    assert (await node_statuses(seeded))[fork.join.id] == NodeRunStatus.PENDING.value

    finished = await drive(seeded)
    assert finished.status == WorkflowRunStatus.SUCCEEDED.value


async def test_a_join_after_an_if_runs_on_the_branch_taken(engine: AsyncEngine):
    entry, decide = _node("core.input"), _node("logic.if", {"condition": "value.go"})
    yes, no = _node("data.map", _map("a", "x")), _node("data.map", _map("b", "y"))
    join = _node("logic.merge")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, decide, yes, no, join),
        edges=(
            _edge(entry, decide),
            _edge(decide, yes, "true"),
            _edge(decide, no, "false"),
            _edge(yes, join),
            _edge(no, join),
        ),
        bindings=(_bind(decide, "value", entry, "out", "payload"),),
    )
    seeded = await _run(engine, graph, {"go": True})

    finished = await drive(seeded)
    statuses = await node_statuses(seeded)

    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert statuses[yes.id] == NodeRunStatus.SUCCEEDED.value
    assert statuses[no.id] == NodeRunStatus.SKIPPED.value
    assert statuses[join.id] == NodeRunStatus.SUCCEEDED.value


@pytest.mark.parametrize("go", [True, False])
async def test_a_mixed_join_runs_with_the_two_legs_of_its_live_group(engine: AsyncEngine, go: bool):
    """If -> (true: A and B) | (false: C); A, B and C all reach one step."""
    entry, decide = _node("core.input"), _node("logic.if", {"condition": "value.go"})
    a, b, c = (_node("data.map", _map(name, "x")) for name in "abc")
    join = _node("data.map", _map("j", "z"))
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, decide, a, b, c, join),
        edges=(
            _edge(entry, decide),
            _edge(decide, a, "true"),
            _edge(decide, b, "true"),
            _edge(decide, c, "false"),
            _edge(a, join),
            _edge(b, join),
            _edge(c, join),
        ),
        bindings=(_bind(decide, "value", entry, "out", "payload"),),
    )
    seeded = await _run(engine, graph, {"go": go})

    finished = await drive(seeded)
    statuses = await node_statuses(seeded)

    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert statuses[join.id] == NodeRunStatus.SUCCEEDED.value
    live, dead = ((a, b), (c,)) if go else ((c,), (a, b))
    assert all(statuses[step.id] == NodeRunStatus.SUCCEEDED.value for step in live)
    assert all(statuses[step.id] == NodeRunStatus.SKIPPED.value for step in dead)


async def test_two_legs_settling_at_once_decide_the_join_exactly_once(engine: AsyncEngine):
    fork = _Fork()
    seeded = await _run(engine, fork.graph)
    await _tick(seeded, fork.entry)

    in_flight = []
    for leg in (fork.a, fork.b):
        row = await _row_of(seeded, leg)
        assert row is not None
        in_flight.append(await begin(seeded, row.id))

    await asyncio.gather(*(settle(seeded, attempt, outcome) for attempt, outcome in in_flight))

    async with seeded.factory() as db:
        join_rows = (
            (
                await db.execute(
                    select(NodeRun).where(
                        NodeRun.workflow_run_id == seeded.run.id,
                        NodeRun.node_instance_id == fork.join.id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(join_rows) == 1
    assert len(await _live_outbox(seeded, fork.join)) == 1
    finished = await drive(seeded)
    assert finished.status == WorkflowRunStatus.SUCCEEDED.value


async def test_a_stored_graph_with_an_unguaranteed_leg_fails_join_incomplete_naming_the_join(
    engine: AsyncEngine,
):
    """A Merge waiting for all, reached on one leg only: stored graphs can still hold it."""
    entry, decide = _node("core.input"), _node("logic.if", {"condition": "value.go"})
    guarded, plain = _node("data.map", _map("a", "x")), _node("data.map", _map("b", "y"))
    merge = _node("logic.merge", {"wait_for": "all"})
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, decide, guarded, plain, merge),
        edges=(
            _edge(entry, decide),
            _edge(entry, plain),
            _edge(decide, guarded, "true"),
            _edge(guarded, merge),
            _edge(plain, merge),
        ),
        bindings=(_bind(decide, "value", entry, "out", "payload"),),
    )
    seeded = await seed_run(engine, graph, run_input={"go": False})

    finished = await drive(seeded)

    assert finished.status == WorkflowRunStatus.FAILED.value
    assert finished.error is not None
    assert finished.error["code"] == "JOIN_INCOMPLETE"
    assert finished.error["details"] == {"node_instance_id": str(merge.id)}
    assert (await node_statuses(seeded))[merge.id] == NodeRunStatus.FAILED.value


async def test_a_merge_waiting_for_all_hands_on_each_branch_under_its_key(engine: AsyncEngine):
    entry = _node("core.input")
    split = _node("logic.split", {"branches": [{"name": "left"}, {"name": "right"}]})
    left, right = _node("data.map", _map("a", "x")), _node("data.map", _map("b", "y"))
    merge = _node(
        "logic.merge",
        {
            "wait_for": "all",
            "branch_keys": [
                {"source_node_id": str(left.id), "source_port": "out", "key": "first"},
                {"source_node_id": str(right.id), "source_port": "out", "key": "second"},
            ],
        },
    )
    out = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, split, left, right, merge, out),
        edges=(
            _edge(entry, split),
            _edge(split, left, "left"),
            _edge(split, right, "right"),
            _edge(left, merge),
            _edge(right, merge),
            _edge(merge, out),
        ),
        bindings=(_bind(out, "structured", merge, "out", "branches"),),
    )
    seeded = await _run(engine, graph)

    finished = await drive(seeded)

    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert finished.output is not None
    assert finished.output["structured"] == {
        "first": {"values": {"a": "x"}},
        "second": {"values": {"b": "y"}},
    }


async def test_a_join_may_read_both_legs_outputs(engine: AsyncEngine):
    fork = _Fork("core.output", {})
    graph = fork.graph.model_copy(
        update={
            "bindings": (
                _bind(fork.join, "text", fork.a, "out", "values", "a"),
                _bind(fork.join, "structured", fork.b, "out", "values"),
            )
        }
    )
    seeded = await _run(engine, graph)

    finished = await drive(seeded)

    assert finished.error is None, finished.error
    assert finished.status == WorkflowRunStatus.SUCCEEDED.value
    assert finished.output is not None
    assert finished.output["text"] == "x"
    assert finished.output["structured"] == {"b": "y"}


# A failure, a cancel, and what a sibling had under way


def _fan(*legs: NodeInstance) -> tuple[NodeInstance, WorkflowGraph]:
    """entry -> every leg, side by side."""
    entry = _node("core.input")
    return entry, WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, *legs),
        edges=tuple(_edge(entry, leg) for leg in legs),
    )


async def _attempts_of(seeded: SeededRun, node: NodeInstance) -> list[NodeAttempt]:
    row = await _row_of(seeded, node)
    assert row is not None
    async with seeded.factory() as db:
        return list(
            (await db.execute(select(NodeAttempt).where(NodeAttempt.node_run_id == row.id)))
            .scalars()
            .all()
        )


async def _awaiting_approval(seeded: SeededRun) -> uuid.UUID:
    """An agent run parked on a tool approval, as an `agent.run` step leaves one."""
    async with seeded.factory() as db:
        agent = Agent(
            id=uuid.uuid4(),
            organization_id=seeded.org.id,
            slug=f"clerk-{uuid.uuid4().hex[:6]}",
            name="Clerk",
            draft_spec={},
        )
        db.add(agent)
        await db.flush()
        agent_run = AgentRun(
            id=uuid.uuid4(),
            organization_id=seeded.org.id,
            agent_id=agent.id,
            surface="api",
            status=RunStatus.AWAITING_APPROVAL.value,
            started_at=datetime.now(UTC),
        )
        db.add(agent_run)
        await db.flush()
        db.add(
            ToolApproval(
                id=uuid.uuid4(),
                organization_id=seeded.org.id,
                run_id=agent_run.id,
                agent_id=agent.id,
                tool_id="send_email",
                status=ApprovalStatus.PENDING.value,
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()
    return agent_run.id


async def _agent_run_status(seeded: SeededRun, agent_run_id: uuid.UUID) -> str:
    async with seeded.factory() as db:
        return (
            await db.execute(select(AgentRun.status).where(AgentRun.id == agent_run_id))
        ).scalar_one()


async def _workflow_approvals(seeded: SeededRun) -> list[str]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(WorkflowApproval.status).where(
                        WorkflowApproval.workflow_run_id == seeded.run.id
                    )
                )
            )
            .scalars()
            .all()
        )


def _ask() -> NodeInstance:
    return _node("human.approval", {"title": "Send the refund?"})


async def test_a_failed_leg_fails_the_run_and_its_sibling_starts_nothing_more(
    engine: AsyncEngine, synthetic_nodes: None
):
    bad, sibling, after = _node("test.fails"), _node("data.map", _map("a", "x")), _node("data.map")
    entry, graph = _fan(bad, sibling)
    graph = graph.model_copy(
        update={"nodes": (*graph.nodes, after), "edges": (*graph.edges, _edge(sibling, after))}
    )
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)

    await _tick(seeded, bad)
    await _tick(seeded, sibling)

    finished = await run_row(seeded)
    statuses = await node_statuses(seeded)
    assert finished.status == WorkflowRunStatus.FAILED.value
    assert finished.error is not None and finished.error["code"] == "LEG_FAILED"
    assert statuses[sibling.id] == NodeRunStatus.CANCELLED.value
    assert after.id not in statuses
    assert await _attempts_of(seeded, sibling) == []


async def test_a_failure_withdraws_a_siblings_queued_backoff_job(
    engine: AsyncEngine, synthetic_nodes: None
):
    retrying, bad = _node("test.retries"), _node("test.fails")
    entry, graph = _fan(retrying, bad)
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)
    await _tick(seeded, retrying)
    retrying_row = await _row_of(seeded, retrying)
    assert retrying_row is not None
    assert retrying_row.waiting_reason == "retry_backoff"
    assert (await run_row(seeded)).status == WorkflowRunStatus.WAITING_RETRY.value

    await _tick(seeded, bad)

    async with seeded.factory() as db:
        jobs = (
            (
                await db.execute(
                    select(BackgroundJob).where(
                        BackgroundJob.kind == "workflow-dispatch-node",
                        BackgroundJob.payload["node_run_id"].astext == str(retrying_row.id),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert jobs and {job.status for job in jobs} == {"cancelled"}
    assert await _live_outbox(seeded, retrying) == []


@pytest.mark.security
async def test_cancel_withdraws_a_siblings_pending_approval_and_stops_its_parked_agent_run(
    engine: AsyncEngine, synthetic_nodes: None
):
    ask, parks = _ask(), _node("test.asks_approval")
    entry, graph = _fan(ask, parks)
    seeded = await seed_run(engine, graph)
    agent_run_id = await _awaiting_approval(seeded)
    _parks_on.append(agent_run_id)
    await _tick(seeded, entry)
    await _tick(seeded, ask)
    await _tick(seeded, parks)
    assert await _workflow_approvals(seeded) == ["pending"]
    assert await _agent_run_status(seeded, agent_run_id) == RunStatus.AWAITING_APPROVAL.value

    async with seeded.factory() as db:
        await WorkflowExecutionService(db).cancel(seeded.ctx, seeded.run.id)
        await db.commit()

    assert await _workflow_approvals(seeded) == ["cancelled"]
    assert await _agent_run_status(seeded, agent_run_id) == RunStatus.CANCELLED.value
    statuses = await node_statuses(seeded)
    assert statuses[ask.id] == statuses[parks.id] == NodeRunStatus.CANCELLED.value
    assert (await run_row(seeded)).status == WorkflowRunStatus.CANCELLED.value


async def _stopped_by_workflow_audits(seeded: SeededRun, ids: list[uuid.UUID]) -> int:
    async with seeded.factory() as db:
        return len(
            (
                await db.execute(
                    select(AppAdminAuditLog).where(
                        AppAdminAuditLog.action == "run.cancelled",
                        AppAdminAuditLog.target_id.in_([str(agent_run_id) for agent_run_id in ids]),
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_cancel_stops_two_parked_agent_steps_and_audits_each(
    engine: AsyncEngine, synthetic_nodes: None
):
    first, second = _node("test.asks_approval"), _node("test.asks_approval")
    entry, graph = _fan(first, second)
    seeded = await seed_run(engine, graph)
    parked = [await _awaiting_approval(seeded), await _awaiting_approval(seeded)]
    _parks_on.extend(parked)
    for node in (entry, first, second):
        await _tick(seeded, node)

    async with seeded.factory() as db:
        await WorkflowExecutionService(db).cancel(seeded.ctx, seeded.run.id)
        await db.commit()

    for agent_run_id in parked:
        assert await _agent_run_status(seeded, agent_run_id) == RunStatus.CANCELLED.value
    assert await _stopped_by_workflow_audits(seeded, parked) == 2
    assert (await run_row(seeded)).status == WorkflowRunStatus.CANCELLED.value


async def test_a_failure_stops_two_parked_agent_steps_and_audits_each(
    engine: AsyncEngine, synthetic_nodes: None
):
    first, second, bad = (
        _node("test.asks_approval"),
        _node("test.asks_approval"),
        _node("test.fails"),
    )
    entry, graph = _fan(first, second, bad)
    seeded = await seed_run(engine, graph)
    parked = [await _awaiting_approval(seeded), await _awaiting_approval(seeded)]
    _parks_on.extend(parked)
    for node in (entry, first, second, bad):
        await _tick(seeded, node)

    for agent_run_id in parked:
        assert await _agent_run_status(seeded, agent_run_id) == RunStatus.CANCELLED.value
    assert await _stopped_by_workflow_audits(seeded, parked) == 2
    assert (await run_row(seeded)).status == WorkflowRunStatus.FAILED.value


@pytest.mark.security
async def test_a_late_sibling_parking_after_the_run_ended_withdraws_its_approval(
    engine: AsyncEngine, synthetic_nodes: None
):
    bad, ask, parks = _node("test.fails"), _ask(), _node("test.asks_approval")
    entry, graph = _fan(bad, ask, parks)
    seeded = await seed_run(engine, graph)
    agent_run_id = await _awaiting_approval(seeded)
    _parks_on.append(agent_run_id)
    await _tick(seeded, entry)
    rows = {leg.id: await _row_of(seeded, leg) for leg in (bad, ask, parks)}
    # The two parking legs are claimed and in flight, their handlers not yet called.
    late = {
        leg.id: await start_attempt(seeded, rows[leg.id].id)  # type: ignore[union-attr]
        for leg in (ask, parks)
    }
    failing = await begin(seeded, rows[bad.id].id)  # type: ignore[union-attr]

    await settle(seeded, *failing)
    assert (await run_row(seeded)).status == WorkflowRunStatus.FAILED.value
    assert await _workflow_approvals(seeded) == []

    # Only now do they park: the request and the agent run are made after the run ended.
    for leg in (ask, parks):
        outcome = await dispatcher.call_handler(late[leg.id])
        await settle(seeded, late[leg.id], outcome)

    assert await _workflow_approvals(seeded) == ["cancelled"]
    assert await _agent_run_status(seeded, agent_run_id) == RunStatus.CANCELLED.value
    statuses = await node_statuses(seeded)
    assert statuses[ask.id] == statuses[parks.id] == NodeRunStatus.CANCELLED.value


@pytest.mark.security
async def test_a_cancelled_sibling_parking_late_leaves_another_branchs_approval_alone(
    engine: AsyncEngine, synthetic_nodes: None
):
    """A routed `stop` loop: the run goes on, so only the late step's own request is withdrawn."""
    entry, loop = _node("core.input"), _node("control.foreach", {"item_error_policy": "stop"})
    loop = loop.model_copy(update={"policy": NodePolicy(on_error="route")})
    item, bad, late = _node("loop.item"), _node("test.fails"), _ask()
    elsewhere, rescued = _ask(), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop, item, bad, late, elsewhere, rescued),
        edges=(
            _edge(entry, loop),
            _edge(entry, elsewhere),
            _edge(loop, item, "body"),
            _edge(loop, rescued, "error"),
            _edge(item, bad),
            _edge(item, late),
        ),
        bindings=(_bind(loop, "items", entry, "out", "payload", "items"),),
    )
    seeded = await seed_run(engine, graph, run_input={"items": ["a"]})
    await _tick(seeded, entry)
    await _tick(seeded, loop)
    await _tick(seeded, elsewhere)
    in_body = {}
    for step in (bad, late):
        async with seeded.factory() as db:
            row = (
                await db.execute(
                    select(NodeRun).where(
                        NodeRun.workflow_run_id == seeded.run.id,
                        NodeRun.node_instance_id == step.id,
                    )
                )
            ).scalar_one()
        in_body[step.id] = row.id
    parked = await start_attempt(seeded, in_body[late.id])
    failing = await begin(seeded, in_body[bad.id])

    await settle(seeded, *failing)
    assert (await run_row(seeded)).status not in {"failed", "cancelled"}
    outcome = await dispatcher.call_handler(parked)
    await settle(seeded, parked, outcome)

    async with seeded.factory() as db:
        by_node = dict(
            (
                await db.execute(
                    select(NodeRun.node_instance_id, WorkflowApproval.status).join(
                        WorkflowApproval, WorkflowApproval.node_run_id == NodeRun.id
                    )
                )
            ).all()
        )
    assert by_node == {late.id: "cancelled", elsewhere.id: "pending"}
    assert (await run_row(seeded)).status == WorkflowRunStatus.WAITING_APPROVAL.value


async def test_a_leg_that_completes_after_the_run_failed_is_recorded_succeeded_without_advancing(
    engine: AsyncEngine, synthetic_nodes: None
):
    bad = _node("test.fails")
    late = _node("data.map", _map("a", "x")).model_copy(update={"quick_log": QuickLog()})
    after = _node("data.map", _map("b", "y"))
    entry, graph = _fan(bad, late)
    graph = graph.model_copy(
        update={"nodes": (*graph.nodes, after), "edges": (*graph.edges, _edge(late, after))}
    )
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)
    in_flight = {}
    for leg in (bad, late):
        row = await _row_of(seeded, leg)
        assert row is not None
        in_flight[leg.id] = await begin(seeded, row.id)

    await settle(seeded, *in_flight[bad.id])
    failed = await run_row(seeded)
    await settle(seeded, *in_flight[late.id])

    after_run = await run_row(seeded)
    late_row = await _row_of(seeded, late)
    assert late_row is not None and failed.ended_at is not None
    assert late_row.status == NodeRunStatus.SUCCEEDED.value
    assert late_row.ended_at is not None and late_row.ended_at > failed.ended_at
    assert after.id not in await node_statuses(seeded)
    assert after_run.error == failed.error
    assert after_run.status == WorkflowRunStatus.FAILED.value
    attempt = (await _attempts_of(seeded, late))[0]
    assert attempt.status == NodeAttemptStatus.COMPLETED.value
    async with seeded.factory() as db:
        lines = (
            (
                await db.execute(
                    select(WorkflowLogEntry).where(WorkflowLogEntry.node_instance_id == late.id)
                )
            )
            .scalars()
            .all()
        )
    assert len(lines) == 1


async def test_two_legs_failing_together_keep_the_first_error(
    engine: AsyncEngine, synthetic_nodes: None
):
    first, second = _node("test.fails"), _node("test.fails_again")
    entry, graph = _fan(first, second)
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)
    in_flight = []
    for leg in (first, second):
        row = await _row_of(seeded, leg)
        assert row is not None
        in_flight.append(await begin(seeded, row.id))

    await asyncio.gather(*(settle(seeded, attempt, outcome) for attempt, outcome in in_flight))

    finished = await run_row(seeded)
    statuses = await node_statuses(seeded)
    winner = first if statuses[first.id] == NodeRunStatus.FAILED.value else second
    assert sorted(statuses[leg.id] for leg in (first, second)) == ["cancelled", "failed"]
    assert finished.error is not None
    assert finished.error["code"] == ("LEG_FAILED" if winner is first else "SECOND_FAILED")


async def test_a_cancelled_nodes_orphaned_attempt_is_not_escalated(
    engine: AsyncEngine, synthetic_nodes: None
):
    leg, sibling = _node("test.records"), _node("data.map", _map("a", "x"))
    entry, graph = _fan(leg, sibling)
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)
    row = await _row_of(seeded, leg)
    assert row is not None
    await begin(seeded, row.id)

    async with seeded.factory() as db:
        run = await db.get(WorkflowRun, seeded.run.id)
        node_run = await db.get(NodeRun, row.id)
        assert run is not None and node_run is not None
        await cleanup.stop_node_work(db, run=run, node_runs=[node_run], now=datetime.now(UTC))
        attempt = (
            await db.execute(select(NodeAttempt).where(NodeAttempt.node_run_id == row.id))
        ).scalar_one()
        await dispatcher.resolve_orphaned_attempt(
            db, run=run, node_run=node_run, attempt=attempt, outbox=None
        )
        await db.commit()

    assert (await _row_of(seeded, leg)).status == NodeRunStatus.CANCELLED.value
    assert (await _attempts_of(seeded, leg))[0].status == NodeAttemptStatus.UNCERTAIN.value
    assert (await run_row(seeded)).status == WorkflowRunStatus.RUNNING.value
    assert await _live_outbox(seeded, leg) == []


# The run's status follows its live steps


async def test_a_sibling_dispatching_does_not_hide_an_approval_wait(engine: AsyncEngine):
    ask, other = _ask(), _node("data.map", _map("a", "x"))
    entry, graph = _fan(ask, other)
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)
    await _tick(seeded, ask)
    assert (await run_row(seeded)).status == WorkflowRunStatus.WAITING_APPROVAL.value

    await _tick(seeded, other)

    waiting = await run_row(seeded)
    assert waiting.status == WorkflowRunStatus.WAITING_APPROVAL.value
    assert waiting.paused_reason == "approval"
    assert (await node_statuses(seeded))[other.id] == NodeRunStatus.SUCCEEDED.value


async def test_a_retry_wait_does_not_hide_a_step_needing_attention(
    engine: AsyncEngine, synthetic_nodes: None
):
    unsure, retrying = _node("test.unsure"), _node("test.retries")
    entry, graph = _fan(unsure, retrying)
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)
    await _tick(seeded, unsure)
    assert (await run_row(seeded)).status == WorkflowRunStatus.NEEDS_ATTENTION.value

    await _tick(seeded, retrying)

    assert (await run_row(seeded)).status == WorkflowRunStatus.NEEDS_ATTENTION.value
    async with seeded.factory() as db:
        kinds = (
            (
                await db.execute(
                    select(WorkflowEvent.kind).where(WorkflowEvent.workflow_run_id == seeded.run.id)
                )
            )
            .scalars()
            .all()
        )
    assert "run_needs_attention" in kinds


async def test_a_needs_attention_branch_lets_its_sibling_finish_and_the_join_waits(
    engine: AsyncEngine, synthetic_nodes: None
):
    unsure, done = _node("test.unsure"), _node("data.map", _map("a", "x"))
    join = _node("data.map", _map("j", "z"))
    entry, graph = _fan(unsure, done)
    graph = graph.model_copy(
        update={
            "nodes": (*graph.nodes, join),
            "edges": (*graph.edges, _edge(unsure, join), _edge(done, join)),
        }
    )
    seeded = await seed_run(engine, graph)

    stopped = await drive(seeded)

    statuses = await node_statuses(seeded)
    assert stopped.status == WorkflowRunStatus.NEEDS_ATTENTION.value
    assert statuses[done.id] == NodeRunStatus.SUCCEEDED.value
    assert statuses[unsure.id] == NodeRunStatus.NEEDS_ATTENTION.value
    assert join.id not in statuses


# A step needing attention is still live work to stop


async def test_cancel_stops_a_sibling_needing_attention(engine: AsyncEngine, synthetic_nodes: None):
    unsure, other = _node("test.unsure"), _node("data.map", _map("a", "x"))
    entry, graph = _fan(unsure, other)
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)
    await _tick(seeded, unsure)
    assert (await run_row(seeded)).status == WorkflowRunStatus.NEEDS_ATTENTION.value

    async with seeded.factory() as db:
        await WorkflowExecutionService(db).cancel(seeded.ctx, seeded.run.id)
        await db.commit()

    statuses = await node_statuses(seeded)
    assert statuses[unsure.id] == NodeRunStatus.CANCELLED.value
    assert statuses[other.id] == NodeRunStatus.CANCELLED.value
    assert (await run_row(seeded)).status == WorkflowRunStatus.CANCELLED.value


async def test_a_failure_stops_a_sibling_needing_attention(
    engine: AsyncEngine, synthetic_nodes: None
):
    unsure, bad = _node("test.unsure"), _node("test.fails")
    entry, graph = _fan(unsure, bad)
    seeded = await seed_run(engine, graph)
    await _tick(seeded, entry)
    await _tick(seeded, unsure)

    await _tick(seeded, bad)

    assert (await run_row(seeded)).status == WorkflowRunStatus.FAILED.value
    assert (await node_statuses(seeded))[unsure.id] == NodeRunStatus.CANCELLED.value
