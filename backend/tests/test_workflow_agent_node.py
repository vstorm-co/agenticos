"""`agent.run`'s handler around a stubbed runner: parking, resuming, and every ending.

The real runner, model and database are `tests/integration/test_workflow_agent_node.py`'s;
what these pin is what the handler makes of each way an agent run can end, which a
real model would need an approval-gated tool or a spent budget to reach.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunStatus
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, Waiting
from app.workflows.nodes.agent_run import AgentRunConfig, AgentRunInput
from app.workflows.nodes.agent_run import _handler as agent_node

pytestmark = pytest.mark.anyio

_AGENT = {"agent_id": str(uuid.uuid4()), "version_id": str(uuid.uuid4())}


def _run(status: RunStatus, *, cost: str = "0", error: str | None = None, partial: bool = False):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status.value,
        cost_usd=Decimal(cost),
        cost_is_partial=partial,
        error=error,
    )


def _dispatch(resumed: uuid.UUID | None = None) -> context.DispatchContext:
    org = uuid.uuid4()
    return context.DispatchContext(
        organization_id=org,
        workflow_run_id=uuid.uuid4(),
        node_run_id=uuid.uuid4(),
        node_instance_id=uuid.uuid4(),
        attempt_no=1,
        auth=AuthContext(user_id=uuid.uuid4(), organization_id=org, role="owner"),
        resumed_agent_run_id=resumed,
    )


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    stub = MagicMock()
    stub.execute = AsyncMock()
    stub.resume = AsyncMock()

    @asynccontextmanager
    async def session():
        yield MagicMock()

    monkeypatch.setattr(agent_node, "get_worker_db_context", session)
    monkeypatch.setattr(agent_node, "AgentRunnerService", lambda _db: stub)
    return stub


async def _call(config: dict[str, Any] | None = None, *, resumed: uuid.UUID | None = None):
    with context.dispatching_as(_dispatch(resumed)) as scope:
        result = await agent_node.handle(
            AgentRunConfig.model_validate({"agent": _AGENT, **(config or {})}),
            AgentRunInput(prompt="Score this lead"),
        )
    return result, scope


@pytest.mark.security
async def test_an_approval_parks_the_node_on_the_agent_run(runner):
    parked = _run(RunStatus.AWAITING_APPROVAL, cost="0.01")
    runner.execute.return_value = ("", parked)

    result, scope = await _call()

    assert isinstance(result, Waiting) and result.reason == "approval"
    assert scope.waiting_agent_run_id == parked.id
    assert scope.cost == Decimal("0.01")


async def test_a_wake_continues_the_same_run_and_books_only_what_it_added(runner, monkeypatch):
    parked_id = uuid.uuid4()
    finished = _run(RunStatus.COMPLETED, cost="0.05")
    runner.resume.return_value = SimpleNamespace(
        output="Approved and sent.", run=finished, structured=None
    )
    monkeypatch.setattr(agent_node, "_cost_so_far", AsyncMock(return_value=Decimal("0.01")))

    result, scope = await _call(resumed=parked_id)

    runner.execute.assert_not_awaited()
    assert runner.resume.await_args.args[1] == parked_id
    assert isinstance(result, Completed) and result.output.text == "Approved and sent."
    assert scope.cost == Decimal("0.04")


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (RunStatus.BUDGET_EXCEEDED, "AGENT_BUDGET_EXCEEDED"),
        (RunStatus.GUARDRAIL_BLOCKED, "AGENT_GUARDRAIL_BLOCKED"),
        (RunStatus.CANCELLED, "AGENT_RUN_FAILED"),
    ],
)
async def test_an_agent_run_that_did_not_finish_fails_the_node(runner, status, code):
    runner.execute.return_value = ("", _run(status, error="stopped"))

    result, _scope = await _call()

    assert isinstance(result, Failed) and result.error.code == code


async def test_a_partial_price_is_reported_as_a_floor(runner):
    runner.execute.return_value = ("ok", _run(RunStatus.COMPLETED, partial=True))

    _result, scope = await _call()

    assert scope.cost_is_partial is True


async def test_a_refusal_the_runner_explains_is_passed_through(runner):
    runner.execute.side_effect = NotFoundError(message="Agent not found", details={"agent_id": "x"})

    result, _scope = await _call()

    assert isinstance(result, Failed)
    assert (result.error.code, result.error.message) == ("NOT_FOUND", "Agent not found")


async def test_an_unexpected_error_says_nothing_of_the_provider(runner):
    runner.execute.side_effect = RuntimeError("POST https://api.example/v1?key=sk-live")

    result, _scope = await _call()

    assert isinstance(result, Failed) and result.error.code == "AGENT_RUN_FAILED"
    assert "sk-live" not in result.error.model_dump_json()


async def test_without_an_agent_or_a_prompt_the_node_fails():
    with context.dispatching_as(_dispatch()):
        result = await agent_node.handle(None, None)
    assert isinstance(result, Failed) and result.error.code == "AGENT_NOT_CONFIGURED"


def test_a_schema_that_is_not_a_json_schema_is_refused_with_the_config():
    with pytest.raises(ValidationError, match="not a valid JSON Schema"):
        AgentRunConfig.model_validate({"agent": _AGENT, "structured_output_schema": {"type": 5}})


def test_an_agent_that_answered_in_text_has_no_object_to_hand_on():
    result = agent_node._structured(None, {"type": "object"})
    assert isinstance(result, Failed) and result.error.code == "STRUCTURED_OUTPUT_MISMATCH"
    assert result.error.message == "The agent answered in text, not with an object"


async def test_the_step_asks_for_its_schema_and_hands_on_the_agents_object(runner):
    schema = {"type": "object", "properties": {"score": {"type": "integer"}}}

    async def execute(*_args, structured, **kwargs):
        assert kwargs["output_schema"] == schema
        structured.append({"score": 87})
        return '```json\n{"score": 87}\n```', _run(RunStatus.COMPLETED)

    runner.execute.side_effect = execute

    result, _scope = await _call(config={"structured_output_schema": schema})

    assert isinstance(result, Completed) and result.output.structured == {"score": 87}


async def test_an_agent_with_its_own_answer_format_hands_its_object_on(runner):
    async def execute(*_args, structured, **kwargs):
        assert kwargs["output_schema"] is None
        structured.append({"tier": "warm"})
        return "", _run(RunStatus.COMPLETED)

    runner.execute.side_effect = execute

    result, _scope = await _call()

    assert isinstance(result, Completed) and result.output.structured == {"tier": "warm"}


async def test_an_unreachable_agent_is_a_problem_on_its_field(monkeypatch):
    registry = MagicMock()
    registry.get_pinned_spec = AsyncMock(
        side_effect=NotFoundError(message="Agent version not found")
    )
    monkeypatch.setattr(agent_node, "AgentRegistryService", lambda _db: registry)

    problems = await agent_node.check_resources(
        MagicMock(),
        AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner"),
        AgentRunConfig.model_validate({"agent": _AGENT}),
    )

    assert problems == [("agent", "Agent version not found")]


async def test_an_object_that_breaks_the_steps_schema_fails_before_the_next_step(runner):
    """The runner asks for the shape and the model is sent back to fix it, but the
    step checks once more: nothing downstream reads an answer of the wrong shape."""
    schema = {"type": "object", "properties": {"score": {"type": "integer"}}}

    async def execute(*_args, structured, **_kwargs):
        structured.append({"score": "high"})
        return "", _run(RunStatus.COMPLETED)

    runner.execute.side_effect = execute

    result, _scope = await _call(config={"structured_output_schema": schema})

    assert isinstance(result, Failed) and result.error.code == "STRUCTURED_OUTPUT_MISMATCH"
    # Where and which rule, never the value: the value is the agent's answer.
    assert result.error.details == {"path": "score", "rule": "type"}
