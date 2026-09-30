"""A Wait that parks on a clock, and a Switch whose branches rejoin at a Merge, end to end."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.workflow_run import DispatchOutbox, NodeRunStatus
from app.workflows.contracts.io import Binding, LiteralValue, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from tests.integration.workflow_run_support import drive, node_statuses, seed_run

pytestmark = pytest.mark.anyio

MAPPING = {
    "mappings": [{"target_field": "label", "source_path": "'mapped'", "coerce_to": "string"}]
}


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
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


def _waiting(config: dict[str, Any], until: object = None) -> tuple[WorkflowGraph, NodeInstance]:
    entry, wait, out = _node("core.input"), _node("flow.wait", config), _node("core.output")
    bindings = [
        Binding(
            target_node_id=out.id,
            target_field="structured",
            source=NodeOutputRef(node_id=wait.id, port="out"),
        )
    ]
    if until is not None:
        bindings.append(
            Binding(target_node_id=wait.id, target_field="until", source=LiteralValue(value=until))
        )
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, wait, out),
        edges=(_edge(entry, wait), _edge(wait, out)),
        bindings=tuple(bindings),
    )
    return graph, wait


class TestWait:
    async def test_a_wait_parks_on_its_clock_and_goes_on_once_it_comes_due(
        self, engine: AsyncEngine
    ):
        graph, wait = _waiting({"seconds": 1})
        seeded = await seed_run(engine, graph)

        parked = await drive(seeded)

        assert parked.status == "running"
        assert (await node_statuses(seeded))[wait.id] == NodeRunStatus.WAITING.value
        async with seeded.factory() as db:
            row = (
                await db.execute(
                    select(DispatchOutbox).where(
                        DispatchOutbox.workflow_run_id == seeded.run.id,
                        DispatchOutbox.status == "pending",
                    )
                )
            ).scalar_one()
        assert row.available_at > datetime.now(UTC)

        await asyncio.sleep(1.2)
        finished = await drive(seeded)
        assert finished.status == "succeeded"

    async def test_a_time_already_past_goes_on_at_once(self, engine: AsyncEngine):
        past = (datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None).isoformat()
        graph, _wait = _waiting({}, until=past)

        finished = await drive(await seed_run(engine, graph))

        assert finished.status == "succeeded"
        assert finished.output["structured"]["waited_until"].startswith(past[:16])

    async def test_a_wait_for_nothing_is_refused(self, engine: AsyncEngine):
        graph, _wait = _waiting({})

        finished = await drive(await seed_run(engine, graph))

        assert finished.error["code"] == "WAIT_NOT_CONFIGURED"

    async def test_a_wait_that_cannot_read_when_it_was_reached_counts_from_now(
        self, engine: AsyncEngine
    ):
        graph, wait = _waiting({"seconds": 60})
        seeded = await seed_run(engine, graph)
        with patch(
            "app.workflows.nodes.flow_wait._handler.workflow_run_repo.get_node_run_by_id",
            new=AsyncMock(return_value=None),
        ):
            parked = await drive(seeded)

        assert parked.status == "running"
        assert (await node_statuses(seeded))[wait.id] == NodeRunStatus.WAITING.value


class TestSwitch:
    async def test_the_chosen_branch_runs_and_the_others_are_skipped_down_to_the_merge(
        self, engine: AsyncEngine
    ):
        entry = _node("core.input")
        switch = _node(
            "logic.switch",
            {
                "rules": [
                    {"name": "poland", "condition": "value.country == 'PL'"},
                    {"name": "germany", "condition": "value.country == 'DE'"},
                ]
            },
        )
        pl, de, other = (_node("data.map", MAPPING) for _ in range(3))
        merge, out = _node("logic.merge"), _node("core.output")
        graph = WorkflowGraph(
            entry_node_id=entry.id,
            nodes=(entry, switch, pl, de, other, merge, out),
            edges=(
                _edge(entry, switch),
                _edge(switch, pl, "poland"),
                _edge(switch, de, "germany"),
                _edge(switch, other, "otherwise"),
                _edge(pl, merge),
                _edge(de, merge),
                _edge(other, merge),
                _edge(merge, out),
            ),
            bindings=(
                Binding(
                    target_node_id=switch.id,
                    target_field="value",
                    source=NodeOutputRef(node_id=entry.id, port="out", field_path=("payload",)),
                ),
                *(
                    Binding(
                        target_node_id=step.id,
                        target_field="source",
                        source=NodeOutputRef(node_id=entry.id, port="out", field_path=("payload",)),
                    )
                    for step in (pl, de, other)
                ),
            ),
        )
        seeded = await seed_run(engine, graph, run_input={"country": "DE"})
        async with async_sessionmaker(engine)() as db:
            await validate_graph(db, seeded.ctx, graph)

        finished = await drive(seeded)

        assert finished.status == "succeeded"
        statuses = await node_statuses(seeded)
        assert statuses[de.id] == NodeRunStatus.SUCCEEDED.value
        assert statuses[pl.id] == statuses[other.id] == NodeRunStatus.SKIPPED.value
