"""The Transform steps chained as the reference's examples chain them, with no code step."""

from __future__ import annotations

import uuid
from itertools import pairwise
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.workflow_run import WorkflowRunStatus
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
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


def _chain(items: list[dict[str, Any]], *steps: NodeInstance) -> WorkflowGraph:
    """The trigger, then `steps` in a line each reading the one before's `items`,
    then the output handing on the last one's."""
    entry, output = _node("core.input"), _node("core.output")
    line = (entry, *steps, output)
    edges = tuple(
        Edge(
            id=uuid.uuid4(),
            source_node_id=source.id,
            source_port="out",
            target_node_id=target.id,
            target_port="in",
        )
        for source, target in pairwise(line)
    )
    reads = [
        Binding(
            target_node_id=step.id,
            target_field="items",
            source=NodeOutputRef(node_id=before.id, port="out", field_path=("items",)),
        )
        for before, step in pairwise(steps)
    ]
    return WorkflowGraph(
        entry_node_id=entry.id,
        nodes=line,
        edges=edges,
        bindings=(
            Binding(
                target_node_id=steps[0].id, target_field="items", source=LiteralValue(value=items)
            ),
            *reads,
            Binding(
                target_node_id=output.id,
                target_field="structured",
                source=NodeOutputRef(node_id=steps[-1].id, port="out", field_path=()),
            ),
        ),
    )


async def _answer(engine: AsyncEngine, graph: WorkflowGraph) -> dict[str, Any]:
    seeded = await seed_run(engine, graph)
    async with async_sessionmaker(engine)() as db:
        await validate_graph(db, seeded.ctx, graph)
    run = await drive(seeded)
    assert run.status == WorkflowRunStatus.SUCCEEDED.value
    return run.output["structured"]


async def test_the_best_leads_once_each_highest_first_named_and_scored(engine: AsyncEngine):
    leads = [
        {"name": "Ada", "email": "ada@x", "score": 70, "notes": "met at a fair"},
        {"name": "Ada L.", "email": "ada@x", "score": 95},
        {"name": "Grace", "email": "grace@x", "score": 88},
        {"name": "Linus", "email": "linus@x", "score": 91},
    ]
    graph = _chain(
        leads,
        _node("transform.remove_duplicates", {"fields": ["email"]}),
        _node("transform.sort", {"by": [{"field": "score", "descending": True}]}),
        _node("transform.limit", {"count": 2}),
        _node(
            "transform.edit_fields",
            {
                "set": [
                    {"name": "name", "expression": "item.name"},
                    {"name": "score", "expression": "item.score"},
                ],
                "only_set": True,
            },
        ),
    )

    answer = await _answer(engine, graph)

    # The first Ada is the one kept; the rest sorted by score, the top two named.
    assert answer["items"] == [{"name": "Linus", "score": 91}, {"name": "Grace", "score": 88}]


async def test_orders_split_into_their_lines_and_totalled_by_region(engine: AsyncEngine):
    orders = [
        {"region": "north", "lines": [{"amount": 10}, {"amount": 5}]},
        {"region": "south", "lines": [{"amount": 7}]},
        {"region": "north", "lines": [{"amount": 1}]},
    ]
    graph = _chain(
        orders,
        _node("transform.split_out", {"field": "lines"}),
        _node(
            "transform.summarize",
            {"group_by": ["region"], "summaries": [{"operation": "sum", "field": "amount"}]},
        ),
    )

    answer = await _answer(engine, graph)

    assert answer["items"] == [
        {"region": "north", "sum_amount": 16},
        {"region": "south", "sum_amount": 7},
    ]
