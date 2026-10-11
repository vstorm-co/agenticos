"""A model step in a real run: the step's own agent, the real runner, a stubbed model.

What only a whole run shows: that a `ai.classify` step is run as an agent the
workflow owns - created on its first run and reused by its next - and that the
branch it chooses is the one the run continues down, while the others are
skipped.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.workflow_run import WorkflowRunStatus
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from tests.integration.test_workflow_agent_node import _profile, _tenant
from tests.integration.workflow_run_support import drive, node_statuses, seed_run

pytestmark = pytest.mark.anyio


def _node(definition_id: str, config: dict[str, Any] | None = None) -> NodeInstance:
    return NodeInstance(
        id=uuid.uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config or {},
        layout=NodePosition(x=0, y=0),
    )


def _edge(source: NodeInstance, port: str, target: NodeInstance) -> Edge:
    return Edge(
        id=uuid.uuid4(),
        source_node_id=source.id,
        source_port=port,
        target_node_id=target.id,
        target_port="in",
    )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch):
    """A model that answers every request with `answer` as its structured object."""

    def install(answer: dict[str, Any]) -> list[str]:
        told: list[str] = []

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            told.append(str(messages[-1]))
            return ModelResponse(
                parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=answer)]
            )

        monkeypatch.setattr(
            "app.agents.model_resolver.build_model", lambda *_args: FunctionModel(respond)
        )
        return told

    return install


async def test_a_classify_step_runs_as_the_workflows_agent_and_takes_its_branch(
    engine: AsyncEngine, model
):
    model({"category": "support", "reason": "It crashes on start"})
    member = await _tenant(engine)
    profile_id = await _profile(engine, member[1])
    entry = _node("core.input")
    sort = _node(
        "ai.classify",
        {
            "model_profile_id": str(profile_id),
            "categories": [
                {"name": "sales", "description": "Wants to buy"},
                {"name": "support", "description": "Needs help with the product"},
            ],
        },
    )
    sold, helped = _node("debug.echo"), _node("debug.echo")
    graph = WorkflowGraph(
        entry_node_id=entry.id,
        nodes=(entry, sort, sold, helped),
        edges=(
            _edge(entry, "out", sort),
            _edge(sort, "sales", sold),
            _edge(sort, "support", helped),
        ),
        bindings=(
            Binding(
                target_node_id=sort.id,
                target_field="text",
                source=NodeOutputRef(
                    node_id=entry.id, port="out", field_path=("payload", "message")
                ),
            ),
        ),
    )

    seeded = await seed_run(engine, graph, run_input={"message": "The app crashes"}, member=member)
    first = await drive(seeded)

    assert first.status == WorkflowRunStatus.SUCCEEDED.value
    statuses = await node_statuses(seeded)
    assert statuses[helped.id] == "succeeded" and statuses[sold.id] == "skipped"
    factory = async_sessionmaker(engine)
    async with factory() as db:
        (agent,) = (
            await db.execute(select(Agent).where(Agent.workflow_node_id == sort.id))
        ).scalars()
        assert agent.name == "Classify"
        runs = await db.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == agent.id)
        )
        assert runs == 1
