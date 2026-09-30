"""Template fields: text with values from earlier steps, checked at publish and rendered at dispatch."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.workflow_run import WorkflowRunStatus
from app.workflows.contracts.io import Binding, NodeOutputRef, TemplateValue
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import drive, seed_run

pytestmark = pytest.mark.anyio

MAPPING = {
    "mappings": [{"target_field": "label", "source_path": "'mapped'", "coerce_to": "string"}]
}


def _node(definition_id: str, config: dict[str, Any] | None = None, **extra: Any) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
        **extra,
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


def _ref(source: NodeInstance, *path: str) -> NodeOutputRef:
    return NodeOutputRef(node_id=source.id, port="out", field_path=path)


def _template(target: NodeInstance, field: str, *parts: str | NodeOutputRef) -> Binding:
    return Binding(target_node_id=target.id, target_field=field, source=TemplateValue(parts=parts))


def _line(
    *template: str | NodeOutputRef, field: str = "text"
) -> tuple[WorkflowGraph, NodeInstance]:
    entry, out = _node("core.input"), _node("core.output")
    parts = tuple(_ref(entry, *part) if isinstance(part, tuple) else part for part in template)
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, out),
        edges=(_edge(entry, out),),
        bindings=(_template(out, field, *parts),),
    )
    return graph, entry


async def _problems(engine: AsyncEngine, graph: WorkflowGraph) -> list[str]:
    seeded = await seed_run(engine, graph)
    async with async_sessionmaker(engine)() as db:
        with pytest.raises(GraphValidationError) as refused:
            await validate_graph(db, seeded.ctx, graph)
    return [problem["message"] for problem in refused.value.details["fields"]]


async def test_a_template_renders_text_with_the_values_it_names(engine: AsyncEngine):
    graph, _entry = _line(
        "New lead: ",
        ("payload", "name"),
        " scored ",
        ("payload", "score"),
        " ",
        ("payload", "tags"),
    )
    seeded = await seed_run(
        engine, graph, run_input={"name": "Ada", "score": 87, "tags": ["eu", "ą"]}
    )
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output["text"] == 'New lead: Ada scored 87 ["eu","ą"]'


async def test_a_placeholder_with_nothing_behind_it_fails_the_step_naming_it(engine: AsyncEngine):
    graph, _entry = _line("Hi ", ("payload", "missing"))
    seeded = await seed_run(engine, graph, run_input={"name": "Ada"})

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.FAILED.value
    assert run.error["code"] == "INVALID_BINDING"
    assert run.error["message"] == "The template in text has nothing for core.input.payload.missing"


async def test_a_template_only_goes_where_text_does(engine: AsyncEngine):
    graph, _entry = _line("Hi ", ("payload", "name"), field="structured")

    assert "A template makes text, and this field does not take text" in await _problems(
        engine, graph
    )


async def test_each_placeholder_is_checked_like_a_binding(engine: AsyncEngine):
    entry, first, later, out = (
        _node("core.input"),
        _node("data.map", MAPPING),
        _node("data.map", MAPPING, disabled=True),
        _node("core.output"),
    )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, first, later, out),
        # Two ways into `later`: switched off, which it would hand on is not known.
        edges=(_edge(entry, first), _edge(first, later), _edge(entry, later), _edge(later, out)),
        bindings=(
            Binding(
                target_node_id=first.id,
                target_field="source",
                source=NodeOutputRef(node_id=entry.id, port="out", field_path=("payload",)),
            ),
            Binding(
                target_node_id=later.id,
                target_field="source",
                source=NodeOutputRef(node_id=entry.id, port="out", field_path=("payload",)),
            ),
            _template(first, "note", "Reads ", _ref(out, "text")),
            _template(out, "text", _ref(first, "nope"), _ref(later, "values")),
        ),
    )

    problems = await _problems(engine, graph)

    assert "This field path does not exist on the source port's schema" in problems
    assert "This reads a step that is switched off, so it would receive nothing" in problems
    assert any("has not" in problem for problem in problems)


async def test_a_placeholder_naming_no_step_of_the_graph_is_refused(engine: AsyncEngine):
    graph, _entry = _line("Hi ")
    stray = graph.model_copy(
        update={
            "bindings": (
                _template(
                    graph.nodes[1], "text", "Hi ", NodeOutputRef(node_id=uuid.uuid4(), port="out")
                ),
            )
        }
    )

    assert "This binding's source node is not in this graph" in await _problems(engine, stray)


async def test_a_template_on_a_step_of_no_known_kind_is_left_to_that_refusal(engine: AsyncEngine):
    graph, entry = _line("Hi ", ("payload", "name"))
    unknown = _node("gone.step")
    stray = graph.model_copy(
        update={
            "nodes": (*graph.nodes, unknown),
            "edges": (*graph.edges, _edge(graph.nodes[1], unknown)),
            "bindings": (
                *graph.bindings,
                _template(unknown, "text", "Hi ", _ref(entry, "payload")),
            ),
        }
    )

    problems = await _problems(engine, stray)

    assert "A template makes text, and this field does not take text" not in problems
