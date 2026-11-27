"""Only real cost caps, including bound Python actions, acquire currency terms."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import JsonValue

from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from app.workflows.python_actions import PYTHON_ACTIONS

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def node(kind: str, config: dict[str, JsonValue]) -> NodeInstance:
    return NodeInstance(
        id=uuid4(),
        definition_id=kind,
        definition_version=1,
        config=config,
        layout=NodePosition(x=0, y=0),
    )


async def test_node_and_python_action_caps_keep_units_but_arbitrary_data_is_untouched() -> None:
    declaration = {"max_cost_usd": {"amount": "1", "currency": "PLN"}}
    capped = node("agent.run", {"max_cost_usd": "0.25", "monetary_inputs": declaration})
    code = node(
        PYTHON_ACTIONS,
        {
            "code": "result = 1",
            "actions": {
                "answer": {
                    "type": "ai.prompt",
                    "version": 1,
                    "config": {"max_cost_usd": "0.25", "monetary_inputs": declaration},
                },
                "literal": {"type": "data.value", "config": {"value": {"max_cost_usd": 999}}},
            },
        },
    )
    data = node("data.value", {"value": {"max_cost_usd": 999}})
    future = node("future.unknown", {"max_cost_usd": "unfinished"})
    graph = WorkflowGraph(entry_node_id=capped.id, nodes=(capped, code, data, future))
    context = AsyncMock(
        return_value=SimpleNamespace(currency="PLN", reporting_units_per_usd=Decimal(4))
    )
    service = WorkflowRegistryService(AsyncMock())
    with patch("app.services.monetary.CurrencyService.context", new=context):
        saved = await service._monetary_graph(uuid4(), graph)
    context.assert_awaited_once()  # one snapshot covers the whole write
    assert isinstance(saved.nodes, tuple)
    assert saved.nodes[0].config["monetary_terms"]["max_cost_usd"]["amount"] == "1"
    assert "monetary_inputs" not in saved.nodes[0].config
    action = saved.nodes[1].config["actions"]["answer"]["config"]
    assert action["monetary_terms"]["max_cost_usd"]["currency"] == "PLN"
    assert "monetary_inputs" not in action
    assert saved.nodes[2:] == graph.nodes[2:]
    with patch(
        "app.services.monetary.CurrencyService.context",
        new=AsyncMock(side_effect=AssertionError("Do not re-quote history")),
    ):
        resaved = await service._monetary_graph(uuid4(), saved, previous=saved)
        imported = await service._monetary_graph(uuid4(), saved, preserve_terms=True)
    assert resaved == imported == saved


async def test_an_incomplete_action_binding_stays_editable_without_interpreting_its_payload() -> (
    None
):
    graph_nodes = tuple(
        node(PYTHON_ACTIONS, config)
        for config in [
            {},
            {"actions": []},
            {
                "actions": {
                    "not_binding": [],
                    "bad_type": {"type": 1},
                    "bad_version": {"type": "agent.run", "version": "unfinished"},
                    "bool_version": {"type": "agent.run", "version": True},
                    "future": {"type": "future.unknown", "config": {"max_cost_usd": 1}},
                    "no_config": {"type": "agent.run"},
                }
            },
        ]
    )
    graph = WorkflowGraph(entry_node_id=graph_nodes[0].id, nodes=graph_nodes)
    assert await WorkflowRegistryService(AsyncMock())._monetary_graph(uuid4(), graph) == graph
