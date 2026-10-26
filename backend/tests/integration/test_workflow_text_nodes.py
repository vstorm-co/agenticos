"""The text nodes in a real run: values enter at the start, a step scores them."""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.workflow_run import WorkflowRunStatus
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import drive, seed_run

pytestmark = pytest.mark.anyio


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port="out",
        target_node_id=target.id,
        target_port="in",
    )


def _bind(target: NodeInstance, field: str, source: NodeInstance, *path: str) -> Binding:
    return Binding(
        target_node_id=target.id,
        target_field=field,
        source=NodeOutputRef(node_id=source.id, port="out", field_path=path),
    )


async def test_two_texts_from_the_run_input_are_scored(engine: AsyncEngine):
    entry = _node(
        "core.input",
        {"fields": [{"name": "draft", "type": "text"}, {"name": "sent", "type": "text"}]},
    )
    compare = _node("text.compare")
    output = _node("core.output")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, compare, output),
        edges=(_edge(entry, compare), _edge(compare, output)),
        bindings=(
            _bind(compare, "a", entry, "payload", "draft"),
            _bind(compare, "b", entry, "payload", "sent"),
            _bind(output, "structured", compare),
        ),
    )
    seeded = await seed_run(
        engine, graph, run_input={"draft": "the quick fox", "sent": "the slow fox"}
    )
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)

    run = await drive(seeded)

    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    assert run.output is not None
    scored = run.output["structured"]
    assert scored["unit"] == "characters"
    assert scored["score"] == pytest.approx(1 - 5 / 13, abs=1e-6)
