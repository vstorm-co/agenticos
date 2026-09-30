"""Error routing, retry policy and durable `control.foreach` scopes, end to end (#1790).

Every graph is published through the real validator and driven through the real
dispatcher against Postgres. What is proved is what an author relies on: a
routed failure reaches its handler and the run goes on, a failure no fallback
may bypass ends the run however it is wired, a loop iterates its frozen list in
order and collects what each iteration yielded, `collect` and `stop` do what
they say, and a worker dying mid-loop resumes at the right iteration without
writing anything twice.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.virtual_table import VirtualTableRecord
from app.db.models.workflow_run import (
    DispatchOutbox,
    NodeAttempt,
    NodeRun,
    NodeRunStatus,
    WorkflowEvent,
    WorkflowRunStatus,
)
from app.schemas.virtual_table import ColumnInput, TableCreate, TableRead
from app.services.virtual_tables.facade import VirtualTableService
from app.services.workflow_execution import WorkflowExecutionService, context, dispatcher
from app.services.workflow_execution.approval_wake import wake_after_approval_decision
from app.workflows._registry import REGISTRY, register
from app.workflows.contracts.definition import NodeDefinition, NodeHandler, Port, RetryGuarantee
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef, TableIORef
from app.workflows.contracts.policy import NodePolicy, RetryPolicy
from app.workflows.contracts.results import Completed, Failed, NodeResult, Waiting, WorkflowError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import (
    SeededRun,
    drive,
    node_statuses,
    run_row,
    seed_member,
    seed_run,
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


def _literal(target: NodeInstance, field: str, value: Any) -> Binding:
    return Binding(target_node_id=target.id, target_field=field, source=LiteralValue(value=value))


ROUTE = NodePolicy(on_error="route")


async def _run(
    engine: AsyncEngine,
    graph: WorkflowGraph,
    run_input: dict[str, Any] | None = None,
    *,
    member: tuple[User, Organization] | None = None,
) -> SeededRun:
    seeded = await seed_run(engine, graph, run_input=run_input, member=member)
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    return seeded


async def _settle(seeded: SeededRun, *, rounds: int = 200) -> Any:
    """Drive the run to an end, waiting out any retry backoff it schedules."""
    for _ in range(rounds):
        run = await drive(seeded)
        if run.status != WorkflowRunStatus.WAITING_RETRY.value:
            return run
        await asyncio.sleep(0.02)
    raise AssertionError("The run was still retrying")


# Synthetic nodes: a failure of a chosen shape, a slow call, a flaky one.


class _Empty(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


_flaky_calls: dict[str, int] = {}
_parks_on: list[uuid.UUID] = []


class _Resumed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_run_id: uuid.UUID


async def _asks_approval(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Parks on the next agent run the test queued; completes once resumed."""
    current = context.current()
    if current.resumed_agent_run_id is None:
        context.report_waiting_agent_run(_parks_on.pop(0))
        return Waiting(reason="approval", resume_token="t")
    return Completed[_Resumed](output=_Resumed(agent_run_id=current.resumed_agent_run_id))


async def _revoked(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    return Failed(
        error=WorkflowError(code="ACCESS_REVOKED", message="No longer allowed", bypassable=False)
    )


async def _slow(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    await asyncio.sleep(5)
    return Completed[_Empty](output=_Empty())  # pragma: no cover - always cut off first


async def _flaky(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    key = "flaky"
    _flaky_calls[key] = _flaky_calls.get(key, 0) + 1
    if _flaky_calls[key] == 1:
        return Failed(error=WorkflowError(code="TRANSIENT", message="Try again", retryable=True))
    return Completed[_Empty](output=_Empty())


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
        _synthetic("test.revoked", _revoked),
        _synthetic("test.slow_read", _slow),
        _synthetic("test.slow_write", _slow, effect="write", guarantee="at_least_once"),
        _synthetic("test.flaky", _flaky),
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
    _flaky_calls.clear()
    yield
    for definition in definitions:
        REGISTRY.pop(definition.id, None)


# Error routing


class _Routed:
    """input -> map (routes errors) -> out: ok | error -> handle -> (not_a_number | default)."""

    def __init__(self) -> None:
        self.entry = _node("core.input")
        self.parse = _node(
            "data.map",
            {"mappings": [{"target_field": "n", "source_path": "source.n", "coerce_to": "number"}]},
            policy=ROUTE,
        )
        self.handle = _node(
            "error.handle",
            {"branches": [{"name": "unreadable", "code": "MAPPING_COERCION_FAILED"}]},
        )
        self.ok = _node("core.output")
        self.unreadable = _node("core.output")
        self.other = _node("core.output")
        self.graph = WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=(self.entry, self.parse, self.handle, self.ok, self.unreadable, self.other),
            edges=(
                _edge(self.entry, self.parse),
                _edge(self.parse, self.ok),
                _edge(self.parse, self.handle, "error"),
                _edge(self.handle, self.unreadable, "unreadable"),
                _edge(self.handle, self.other, "default"),
            ),
            bindings=(
                _bind(self.parse, "source", self.entry, "out", "payload"),
                _bind(self.ok, "structured", self.parse, "out", "values"),
                _bind(self.unreadable, "text", self.handle, "unreadable", "code"),
                _bind(self.other, "text", self.handle, "default", "code"),
            ),
        )


async def test_a_routed_failure_reaches_its_branch_and_the_run_succeeds(engine: AsyncEngine):
    graph = _Routed()
    seeded = await _run(engine, graph.graph, {"n": "not a number"})

    run = await drive(seeded)
    statuses = await node_statuses(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None and run.output["text"] == "MAPPING_COERCION_FAILED"
    assert statuses[graph.parse.id] == NodeRunStatus.FAILED.value
    assert statuses[graph.ok.id] == NodeRunStatus.SKIPPED.value
    assert statuses[graph.other.id] == NodeRunStatus.SKIPPED.value


async def test_a_step_that_succeeds_leaves_its_error_path_skipped(engine: AsyncEngine):
    graph = _Routed()
    seeded = await _run(engine, graph.graph, {"n": "42"})

    run = await drive(seeded)
    statuses = await node_statuses(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None and run.output["structured"] == {"n": 42}
    assert statuses[graph.handle.id] == NodeRunStatus.SKIPPED.value


async def test_the_error_and_the_success_path_rejoin_at_a_merge(engine: AsyncEngine):
    entry, merge, out = _node("core.input"), _node("logic.merge"), _node("core.output")
    parse = _node(
        "data.map",
        {"mappings": [{"target_field": "n", "source_path": "source.n", "coerce_to": "number"}]},
        policy=ROUTE,
    )
    handle = _node("error.handle")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, parse, handle, merge, out),
        edges=(
            _edge(entry, parse),
            _edge(parse, merge),
            _edge(parse, handle, "error"),
            _edge(handle, merge, "default"),
            _edge(merge, out),
        ),
        bindings=(
            _bind(parse, "source", entry, "out", "payload"),
            _bind(out, "structured", merge, "out", "value"),
        ),
    )

    failed = await drive(await _run(engine, graph, {"n": "x"}))
    passed = await drive(await _run(engine, graph, {"n": "7"}))

    assert failed.status == passed.status == WorkflowRunStatus.SUCCEEDED.value
    assert failed.output is not None and failed.output["structured"]["branch"] == "default"
    assert passed.output is not None and passed.output["structured"] == {"values": {"n": 7}}


@pytest.mark.security
async def test_a_failure_no_fallback_may_bypass_ends_the_run_however_it_is_wired(
    engine: AsyncEngine, synthetic_nodes: None
):
    entry, revoked, handle = (
        _node("core.input"),
        _node("test.revoked", policy=ROUTE),
        _node("error.handle"),
    )
    out = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, revoked, handle, out),
        edges=(
            _edge(entry, revoked),
            _edge(revoked, handle, "error"),
            _edge(handle, out, "default"),
        ),
    )
    seeded = await _run(engine, graph)

    run = await drive(seeded)
    statuses = await node_statuses(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "ACCESS_REVOKED"
    assert handle.id not in statuses


async def test_error_raise_fails_with_only_what_the_author_configured(engine: AsyncEngine):
    entry = _node("core.input")
    raise_ = _node("error.raise", {"code": "ORDER_REJECTED", "message": "Over the limit"})
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, raise_),
        edges=(_edge(entry, raise_),),
        bindings=(_bind(raise_, "details", entry, "out", "payload"),),
    )

    run = await drive(await _run(engine, graph, {"order": "A-1"}))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error == {
        "code": "ORDER_REJECTED",
        "message": "Over the limit",
        "details": {"order": "A-1"},
        "retryable": False,
        "bypassable": True,
    }


# Retry and timeout policy


async def test_a_node_retry_policy_decides_how_often_a_failure_is_retried(
    engine: AsyncEngine, synthetic_nodes: None
):
    policy = NodePolicy(retry=RetryPolicy(max_attempts=2, backoff="fixed", base_delay_seconds=0.01))
    entry, flaky = _node("core.input"), _node("test.flaky", policy=policy)
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, flaky), edges=(_edge(entry, flaky),)
    )
    seeded = await _run(engine, graph)

    run = await _settle(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert _flaky_calls["flaky"] == 2


async def test_one_attempt_means_the_first_failure_is_final(
    engine: AsyncEngine, synthetic_nodes: None
):
    entry, flaky = (
        _node("core.input"),
        _node("test.flaky", policy=NodePolicy(retry=RetryPolicy(max_attempts=1))),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id, nodes=(entry, flaky), edges=(_edge(entry, flaky),)
    )

    run = await drive(await _run(engine, graph))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "TRANSIENT"


async def test_a_read_past_its_time_limit_fails_as_a_timeout(
    engine: AsyncEngine, synthetic_nodes: None
):
    policy = NodePolicy(timeout_seconds=0.05, retry=RetryPolicy(max_attempts=1))
    entry, slow = _node("core.input"), _node("test.slow_read", policy=policy)
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, slow), edges=(_edge(entry, slow),))

    run = await drive(await _run(engine, graph))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "NODE_TIMEOUT"


async def test_a_write_past_its_time_limit_is_uncertain_not_retried(
    engine: AsyncEngine, synthetic_nodes: None
):
    entry, slow = (
        _node("core.input"),
        _node("test.slow_write", policy=NodePolicy(timeout_seconds=0.05)),
    )
    graph = WorkflowGraph(entry_node_id=entry.id, nodes=(entry, slow), edges=(_edge(entry, slow),))

    run = await drive(await _run(engine, graph))

    assert run.status == WorkflowRunStatus.NEEDS_ATTENTION.value


# Loops


class _Loop:
    """input -> foreach(items) -body-> item -> map -> yield ; foreach -done-> output."""

    def __init__(self, *, policy: str = "stop", fail_on: str | None = None) -> None:
        self.entry = _node("core.input")
        self.loop = _node("control.foreach", {"item_error_policy": policy})
        self.item = _node("loop.item")
        self.map = _node(
            "data.map",
            {
                "mappings": [
                    {
                        "target_field": "name",
                        "source_path": "source.item.name",
                        "coerce_to": "string",
                    },
                    {"target_field": "at", "source_path": "source.index", "coerce_to": "integer"},
                ]
            },
        )
        self.yield_ = _node("loop.yield")
        self.out = _node("core.output")
        nodes = [self.entry, self.loop, self.item, self.map, self.yield_, self.out]
        edges = [
            _edge(self.entry, self.loop),
            _edge(self.loop, self.item, "body"),
            _edge(self.loop, self.out, "done"),
        ]
        bindings = [
            _bind(self.loop, "items", self.entry, "out", "payload", "items"),
            _bind(self.map, "source", self.item, "out"),
            _bind(self.yield_, "value", self.map, "out", "values"),
            _bind(self.out, "structured", self.loop, "done"),
        ]
        if fail_on is None:
            edges += [_edge(self.item, self.map), _edge(self.map, self.yield_)]
        else:
            # An item named `fail_on` is refused by `error.raise` instead.
            self.decide = _node("logic.if", {"condition": f"value.item.name == '{fail_on}'"})
            self.refuse = _node("error.raise", {"code": "BAD_ITEM", "message": "Refused"})
            nodes += [self.decide, self.refuse]
            edges += [
                _edge(self.item, self.decide),
                _edge(self.decide, self.refuse, "true"),
                _edge(self.decide, self.map, "false"),
                _edge(self.map, self.yield_),
            ]
            bindings.append(_bind(self.decide, "value", self.item, "out"))
        self.graph = WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=tuple(nodes),
            edges=tuple(edges),
            bindings=tuple(bindings),
        )


ITEMS = [{"name": "ada"}, {"name": "grace"}, {"name": "linus"}]


async def _body_rows(seeded: SeededRun, node_id: uuid.UUID) -> list[NodeRun]:
    async with seeded.factory() as db:
        return list(
            (
                await db.execute(
                    select(NodeRun).where(
                        NodeRun.workflow_run_id == seeded.run.id,
                        NodeRun.node_instance_id == node_id,
                    )
                )
            ).scalars()
        )


async def test_a_loop_runs_its_body_once_per_item_in_order_and_collects_the_results(
    engine: AsyncEngine,
):
    loop = _Loop()
    seeded = await _run(engine, loop.graph, {"items": ITEMS})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    assert run.output["structured"] == {
        "results": [
            {"name": "ada", "at": 0},
            {"name": "grace", "at": 1},
            {"name": "linus", "at": 2},
        ],
        "errors": [],
        "count": 3,
    }
    rows = await _body_rows(seeded, loop.map.id)
    assert sorted(row.scope_path[0]["index"] for row in rows) == [0, 1, 2]
    assert {row.scope_path[0]["loop_node_id"] for row in rows} == {str(loop.loop.id)}


async def test_an_empty_list_runs_no_body_and_gives_empty_results(engine: AsyncEngine):
    loop = _Loop()
    seeded = await _run(engine, loop.graph, {"items": []})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    assert run.output["structured"] == {"results": [], "errors": [], "count": 0}
    assert await _body_rows(seeded, loop.item.id) == []


async def test_collect_records_a_failed_item_in_its_place_and_carries_on(engine: AsyncEngine):
    loop = _Loop(policy="collect", fail_on="grace")
    seeded = await _run(engine, loop.graph, {"items": ITEMS})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    structured = run.output["structured"]
    assert structured["results"] == [{"name": "ada", "at": 0}, None, {"name": "linus", "at": 2}]
    assert structured["errors"] == [
        {"index": 1, "code": "BAD_ITEM", "message": "Refused", "details": {}}
    ]


async def test_stop_fails_the_loop_at_the_first_failed_item_naming_its_scope(
    engine: AsyncEngine,
):
    loop = _Loop(policy="stop", fail_on="grace")
    seeded = await _run(engine, loop.graph, {"items": ITEMS})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "BAD_ITEM"
    assert run.error["details"]["scope_path"] == [{"loop_node_id": str(loop.loop.id), "index": 1}]
    # The third item never started.
    assert sorted(r.scope_path[0]["index"] for r in await _body_rows(seeded, loop.item.id)) == [
        0,
        1,
    ]
    assert (await node_statuses(seeded))[loop.loop.id] == NodeRunStatus.FAILED.value


async def test_a_list_over_the_ceiling_is_refused_whole(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("app.core.config.settings.WORKFLOW_FOREACH_MAX_ITEMS", 2)
    loop = _Loop()

    run = await drive(await _run(engine, loop.graph, {"items": ITEMS}))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "FOREACH_TOO_MANY_ITEMS"
    assert run.error["details"] == {"limit": 2, "count": 3}


async def test_a_run_past_its_node_run_ceiling_fails_rather_than_growing(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    # Four top-level rows exist by the second iteration; each adds three body rows.
    monkeypatch.setattr("app.core.config.settings.WORKFLOW_RUN_MAX_NODE_RUNS", 8)
    loop = _Loop()

    run = await drive(await _run(engine, loop.graph, {"items": ITEMS}))

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error is not None and run.error["code"] == "NODE_RUN_LIMIT"


async def test_nested_loops_keep_each_iteration_in_its_own_scope(engine: AsyncEngine):
    entry, outer, outer_item = _node("core.input"), _node("control.foreach"), _node("loop.item")
    inner, inner_item, inner_yield = (
        _node("control.foreach"),
        _node("loop.item"),
        _node("loop.yield"),
    )
    outer_yield, out = _node("loop.yield"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, outer, outer_item, inner, inner_item, inner_yield, outer_yield, out),
        edges=(
            _edge(entry, outer),
            _edge(outer, outer_item, "body"),
            _edge(outer_item, inner),
            _edge(inner, inner_item, "body"),
            _edge(inner_item, inner_yield),
            _edge(inner, outer_yield, "done"),
            _edge(outer, out, "done"),
        ),
        bindings=(
            _bind(outer, "items", entry, "out", "payload", "rows"),
            _bind(inner, "items", outer_item, "out", "item"),
            # The inner body reads the outer iteration's index, an enclosing scope.
            _bind(inner_yield, "value", outer_item, "out", "index"),
            _bind(outer_yield, "value", inner, "done", "results"),
            _bind(out, "structured", outer, "done"),
        ),
    )

    run = await drive(await _run(engine, graph, {"rows": [["a", "b"], ["c"], []]}))

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    assert run.output["structured"]["results"] == [[0, 0], [1], []]


# Durability


async def _world(engine: AsyncEngine) -> tuple[tuple[User, Organization], TableRead]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        member = await seed_member(db)
        table = await VirtualTableService(db).create_table(
            AuthContext(user_id=member[0].id, organization_id=member[1].id, role="owner"),
            TableCreate(name="Guests", columns=[ColumnInput(label="Name", type="text")]),
        )
        await db.commit()
    return member, table


def _writing_loop(table: TableRead) -> tuple[WorkflowGraph, NodeInstance, NodeInstance]:
    """input -> foreach -body-> item -> map -> table.record.create -> yield."""
    entry, loop, item = _node("core.input"), _node("control.foreach"), _node("loop.item")
    map_ = _node(
        "data.map",
        {
            "mappings": [
                {"target_field": "Name", "source_path": "source.item", "coerce_to": "string"}
            ]
        },
    )
    create = _node(
        "table.record.create",
        {
            "table": TableIORef(table_id=table.id, schema_version=table.schema_version).model_dump(
                mode="json"
            )
        },
    )
    yield_ = _node("loop.yield")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop, item, map_, create, yield_),
        edges=(
            _edge(entry, loop),
            _edge(loop, item, "body"),
            _edge(item, map_),
            _edge(map_, create),
            _edge(create, yield_),
        ),
        bindings=(
            _bind(loop, "items", entry, "out", "payload", "names"),
            _bind(map_, "source", item, "out"),
            _bind(create, "values", map_, "out", "values"),
            _bind(yield_, "value", create, "out", "record_id"),
        ),
    )
    return graph, loop, create


async def _pending(seeded: SeededRun) -> uuid.UUID | None:
    async with seeded.factory() as db:
        return (
            await db.execute(
                select(DispatchOutbox.node_run_id)
                .where(
                    DispatchOutbox.workflow_run_id == seeded.run.id,
                    DispatchOutbox.status == "pending",
                )
                .order_by(DispatchOutbox.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()


async def _node_run_of(seeded: SeededRun, node_run_id: uuid.UUID) -> NodeRun:
    async with seeded.factory() as db:
        return (await db.execute(select(NodeRun).where(NodeRun.id == node_run_id))).scalar_one()


async def test_a_worker_dying_mid_write_resumes_the_same_iteration_and_writes_once(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
):
    # The reclaimed write is retried after the ordinary backoff, shortened here.
    monkeypatch.setattr("app.core.config.settings.WORKFLOW_RETRY_BACKOFF_BASE_SECONDS", 0.01)
    member, table = await _world(engine)
    graph, loop, create = _writing_loop(table)
    seeded = await _run(engine, graph, {"names": ["ada", "grace", "linus"]}, member=member)

    # Drive until the second iteration's write is next, then die inside it: the
    # handler's write lands, the settle never happens.
    while True:
        node_run_id = await _pending(seeded)
        assert node_run_id is not None
        row = await _node_run_of(seeded, node_run_id)
        if row.node_instance_id == create.id and row.scope_path[0]["index"] == 1:
            break
        await tick(seeded, node_run_id)
    async with seeded.factory() as db:
        claim = await dispatcher.claim(db, node_run_id=node_run_id)
        await db.commit()
    assert claim is not None and claim.claimed_by is not None
    async with seeded.factory() as db:
        begun = await dispatcher.begin_attempt(
            db, workflow_run_id=seeded.run.id, node_run_id=node_run_id, token=claim.claimed_by
        )
        await db.commit()
    assert begun is not None
    await dispatcher.call_handler(begun)
    # The lease runs out with nobody renewing it.
    async with seeded.factory() as db:
        await db.execute(
            update(DispatchOutbox)
            .where(DispatchOutbox.node_run_id == node_run_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1), status="pending")
        )
        await db.commit()

    run = await drive(seeded)
    for _ in range(100):
        if run.status != WorkflowRunStatus.RUNNING.value:
            break
        await asyncio.sleep(0.02)
        run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    async with seeded.factory() as db:
        written = await db.scalar(
            select(func.count())
            .select_from(VirtualTableRecord)
            .where(VirtualTableRecord.table_id == table.id)
        )
        # Every iteration's `loop.item` was written once: none restarted.
        item_attempts = await db.scalar(
            select(func.count())
            .select_from(NodeAttempt)
            .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
            .where(
                NodeRun.workflow_run_id == seeded.run.id,
                NodeRun.node_instance_id == graph.nodes[2].id,
            )
        )
        started = await db.scalar(
            select(func.count())
            .select_from(WorkflowEvent)
            .where(
                WorkflowEvent.workflow_run_id == seeded.run.id,
                WorkflowEvent.kind == "iteration_started",
            )
        )
    assert written == 3
    assert item_attempts == 3
    assert started == 3


async def test_the_loop_reads_the_list_it_froze_not_its_source(engine: AsyncEngine):
    loop = _Loop()
    seeded = await _run(engine, loop.graph, {"items": ITEMS})
    # Run up to the first iteration, then rewrite the loop's source output.
    while (node_run_id := await _pending(seeded)) is not None:
        row = await _node_run_of(seeded, node_run_id)
        if row.scope_path:
            break
        await tick(seeded, node_run_id)
    async with seeded.factory() as db:
        entry_run = (
            await db.execute(
                select(NodeRun).where(
                    NodeRun.workflow_run_id == seeded.run.id,
                    NodeRun.node_instance_id == loop.entry.id,
                )
            )
        ).scalar_one()
        await db.execute(
            update(NodeAttempt)
            .where(NodeAttempt.node_run_id == entry_run.id)
            .values(
                result={
                    "status": "completed",
                    "output": {"payload": {"items": []}, "triggered_by": "api"},
                }
            )
        )
        await db.commit()

    run = await drive(seeded)

    assert run.output is not None and run.output["structured"]["count"] == 3


async def test_the_run_finishes_only_with_the_loop(engine: AsyncEngine):
    loop = _Loop()
    seeded = await _run(engine, loop.graph, {"items": ITEMS[:1]})

    # Before the only iteration's yield runs, the loop is still `running`.
    while (node_run_id := await _pending(seeded)) is not None:
        row = await _node_run_of(seeded, node_run_id)
        if row.node_instance_id == loop.yield_.id:
            break
        await tick(seeded, node_run_id)
    assert (await node_statuses(seeded))[loop.loop.id] == NodeRunStatus.RUNNING.value
    assert (await run_row(seeded)).status == WorkflowRunStatus.RUNNING.value

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value


async def _awaiting_approval(seeded: SeededRun) -> uuid.UUID:
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


async def _approve(seeded: SeededRun, agent_run_id: uuid.UUID) -> None:
    async with seeded.factory() as db:
        await db.execute(
            update(ToolApproval)
            .where(ToolApproval.run_id == agent_run_id)
            .values(status=ApprovalStatus.APPROVED.value)
        )
        await db.commit()
    await wake_after_approval_decision(agent_run_id, organization_id=seeded.org.id)


async def test_an_approval_inside_an_iteration_resumes_that_iteration(
    engine: AsyncEngine, synthetic_nodes: None
):
    entry, loop, item = _node("core.input"), _node("control.foreach"), _node("loop.item")
    ask, yield_, out = _node("test.asks_approval"), _node("loop.yield"), _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, loop, item, ask, yield_, out),
        edges=(
            _edge(entry, loop),
            _edge(loop, item, "body"),
            _edge(item, ask),
            _edge(ask, yield_),
            _edge(loop, out, "done"),
        ),
        bindings=(
            _bind(loop, "items", entry, "out", "payload", "items"),
            _bind(yield_, "value", ask, "out", "agent_run_id"),
            _bind(out, "structured", loop, "done"),
        ),
    )
    seeded = await _run(engine, graph, {"items": ["first", "second"]})
    first, second = await _awaiting_approval(seeded), await _awaiting_approval(seeded)
    _parks_on.extend([first, second])

    parked = await drive(seeded)
    await _approve(seeded, first)
    parked_again = await drive(seeded)
    await _approve(seeded, second)
    run = await drive(seeded)

    assert parked.status == parked_again.status == WorkflowRunStatus.WAITING_APPROVAL.value
    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    assert run.output["structured"]["results"] == [str(first), str(second)]


async def test_a_run_lists_every_step_it_took_with_each_iterations_error(engine: AsyncEngine):
    loop = _Loop(policy="collect", fail_on="grace")
    seeded = await _run(engine, loop.graph, {"items": ITEMS})
    await drive(seeded)

    async with seeded.factory() as db:
        listed = await WorkflowExecutionService(db).node_runs(seeded.ctx, seeded.run.id)

    refused = [row for row in listed.items if row.node_instance_id == loop.refuse.id]
    items = [row for row in listed.items if row.node_instance_id == loop.item.id]
    assert listed.total == len(listed.items)
    assert [row.scope_path[0]["index"] for row in items] == [0, 1, 2]
    assert len(refused) == 3
    failed = next(row for row in refused if row.status == NodeRunStatus.FAILED)
    assert failed.error is not None and failed.error["code"] == "BAD_ITEM"
    assert failed.attempts == 1 and failed.scope_path[0]["index"] == 1
    # What a step produced is there to read back; a failed try produced nothing.
    assert failed.output is None
    passed = next(row for row in items if row.status == NodeRunStatus.SUCCEEDED)
    assert isinstance(passed.output, dict)


async def test_a_run_answers_with_the_graph_it_executes_its_loops_derived(engine: AsyncEngine):
    loop = _Loop()
    seeded = await _run(engine, loop.graph, {"items": []})

    async with seeded.factory() as db:
        answered = await WorkflowExecutionService(db).graph(seeded.ctx, seeded.run.id)

    graph = WorkflowGraph.model_validate(answered.graph)
    assert {node.id for node in graph.nodes} == {node.id for node in loop.graph.nodes}
    assert [scope.scope_node_id for scope in graph.scopes] == [loop.loop.id]
