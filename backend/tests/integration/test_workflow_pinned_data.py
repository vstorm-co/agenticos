"""Pinned data and a single step's test: what a test run hands on without running a step."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.workflow_run import NodeRunStatus, WorkflowRunMode, WorkflowRunStatus
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow_run import WorkflowRunStart, WorkflowStepTest
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.errors import StepNotTestableError
from app.workflows.graph.model import (
    MAX_PINNED_BYTES,
    Edge,
    NodeInstance,
    NodePosition,
    WorkflowGraph,
)
from app.workflows.graph.step import step_subgraph
from app.workflows.graph.validate import derive_scopes, validate_graph
from tests.integration.workflow_run_support import drive, node_statuses, seed_run

pytestmark = pytest.mark.anyio

MAPPING = {
    "mappings": [{"target_field": "label", "source_path": "'mapped'", "coerce_to": "string"}]
}
PINNED = {"values": {"label": "pinned"}}


def _node(definition_id: str, config: dict[str, Any] | None = None, **extra: Any) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
        **extra,
    )


def _edge(source: NodeInstance, target: NodeInstance, port: str = "out") -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


def _bind(target: NodeInstance, field: str, source: NodeInstance, *path: str) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port="out", field_path=tuple(path)),
    )


class _Line:
    """input -> map -> output, the output reading what the map made."""

    def __init__(self, **map_extra: Any) -> None:
        self.entry = _node("core.input")
        self.map = _node("data.map", MAPPING, **map_extra)
        self.out = _node("core.output")
        self.graph = WorkflowGraph(
            entry_node_id=self.entry.id,
            nodes=(self.entry, self.map, self.out),
            edges=(_edge(self.entry, self.map), _edge(self.map, self.out)),
            bindings=(
                _bind(self.map, "source", self.entry, "payload"),
                _bind(self.out, "text", self.map, "values", "label"),
            ),
        )


class TestPinnedData:
    async def test_a_test_run_hands_on_the_pinned_data_instead_of_running_the_step(
        self, engine: AsyncEngine
    ):
        line = _Line(pinned_output=PINNED)
        seeded = await seed_run(engine, line.graph)

        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        assert run.output["text"] == "pinned"

    async def test_a_real_run_runs_the_step_whatever_is_pinned(self, engine: AsyncEngine):
        line = _Line(pinned_output=PINNED)
        seeded = await seed_run(engine, line.graph)
        async with seeded.factory() as db:
            await workflow_run_repo.update_run(
                db, run=seeded.run, update_data={"mode": WorkflowRunMode.REAL.value}
            )
            await db.commit()

        run = await drive(seeded)

        assert run.output["text"] == "mapped"

    async def test_a_deciding_step_decides_whatever_is_pinned(self, engine: AsyncEngine):
        entry = _node("core.input")
        decide = _node(
            "logic.if", {"condition": "value.name == 'Ada'"}, pinned_output={"nothing": True}
        )
        out = _node("core.output")
        graph = WorkflowGraph(
            entry_node_id=entry.id,
            nodes=(entry, decide, out),
            edges=(_edge(entry, decide), _edge(decide, out, "true")),
            bindings=(
                _bind(decide, "value", entry, "payload"),
                _bind(out, "text", entry, "payload", "name"),
            ),
        )
        seeded = await seed_run(engine, graph, run_input={"name": "Ada"})

        run = await drive(seeded)

        assert (run.status, run.output["text"]) == (WorkflowRunStatus.SUCCEEDED.value, "Ada")

    def test_pinned_data_has_a_size_limit(self):
        with pytest.raises(ValidationError, match="Pinned data may take at most"):
            _node("data.map", MAPPING, pinned_output={"text": "x" * MAX_PINNED_BYTES})


class TestTheStepsGraph:
    def test_it_keeps_the_step_and_what_leads_to_it_and_pins_what_is_known(self):
        line = _Line()
        known = {line.entry.id: {"payload": {"name": "Ada"}}}

        graph = step_subgraph(line.graph, line.map.id, known)

        assert [node.id for node in graph.nodes] == [line.entry.id, line.map.id]
        assert graph.node_by_id[line.entry.id].pinned_output == known[line.entry.id]
        assert [edge.target_node_id for edge in graph.edges] == [line.map.id]
        assert [binding.target_node_id for binding in graph.bindings] == [line.map.id]

    def test_the_step_itself_runs_and_an_authors_pin_wins_over_the_last_run(self):
        entry = _node("core.input", pinned_output={"payload": {"name": "Pinned"}})
        middle = _node("data.map", MAPPING, pinned_output=PINNED)
        graph = WorkflowGraph(
            entry_node_id=entry.id, nodes=(entry, middle), edges=(_edge(entry, middle),)
        )

        narrowed = step_subgraph(graph, middle.id, {entry.id: {"payload": {"name": "Last"}}})

        assert narrowed.node_by_id[entry.id].pinned_output == {"payload": {"name": "Pinned"}}
        assert narrowed.node_by_id[middle.id].pinned_output is None

    def test_a_loop_before_the_step_comes_whole_and_runs(self):
        entry, loop, item = _node("core.input"), _node("control.foreach"), _node("loop.item")
        out = _node("core.output")
        graph = derive_scopes(
            WorkflowGraph(
                entry_node_id=entry.id,
                nodes=(entry, loop, item, out),
                edges=(_edge(entry, loop), _edge(loop, item, "body"), _edge(loop, out, "done")),
            )
        )

        narrowed = step_subgraph(graph, out.id, {loop.id: {"done": []}})

        assert {node.id for node in narrowed.nodes} == {entry.id, loop.id, item.id, out.id}
        assert narrowed.node_by_id[loop.id].pinned_output is None
        assert [scope.scope_node_id for scope in narrowed.scopes] == [loop.id]

        with pytest.raises(StepNotTestableError) as refused:
            step_subgraph(graph, item.id, {})
        assert refused.value.details["reason"] == "inside_a_loop"

    def test_a_step_the_draft_does_not_have_is_refused(self):
        with pytest.raises(StepNotTestableError) as refused:
            step_subgraph(_Line().graph, uuid.uuid4(), {})

        assert refused.value.details["reason"] == "unknown_step"

    async def test_testing_a_step_runs_it_on_the_known_data_and_nothing_after_it(
        self, engine: AsyncEngine
    ):
        line = _Line()
        graph = step_subgraph(line.graph, line.map.id, {line.entry.id: {"payload": {}}})
        seeded = await seed_run(engine, graph)
        async with async_sessionmaker(engine)() as db:
            await validate_graph(db, seeded.ctx, line.graph)

        run = await drive(seeded)

        assert run.status == WorkflowRunStatus.SUCCEEDED.value
        statuses = await node_statuses(seeded)
        assert statuses == {
            line.entry.id: NodeRunStatus.SUCCEEDED.value,
            line.map.id: NodeRunStatus.SUCCEEDED.value,
        }


class TestTheRequest:
    def test_only_a_test_run_tests_a_step(self):
        with pytest.raises(ValidationError, match="Only a test run can test a single step"):
            WorkflowRunStart(workflow_id=uuid.uuid4(), step=WorkflowStepTest(node_id=uuid.uuid4()))

    def test_known_outputs_are_bounded_each_and_together(self):
        with pytest.raises(ValidationError, match="Pinned data may take at most"):
            WorkflowStepTest(
                node_id=uuid.uuid4(), outputs={uuid.uuid4(): {"text": "x" * MAX_PINNED_BYTES}}
            )
        half = {"text": "x" * (MAX_PINNED_BYTES // 2)}
        with pytest.raises(ValidationError, match="Known outputs may take at most"):
            WorkflowStepTest(node_id=uuid.uuid4(), outputs={uuid.uuid4(): half for _ in range(10)})
