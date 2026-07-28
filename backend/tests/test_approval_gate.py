"""Tests for the approval gate — what happens between asking and acting.

The gate is the only thing standing between a model deciding to send an email
and an email being sent, so what is guarded here is mostly refusal: a call with
no approver refuses, a rejected call refuses, and an approved call runs the
arguments a person read rather than the ones the model produced on the replay.

The last test is the one that would have caught the bug this exists to fix: a
parked run that never continues. It drives a real agent through park and resume.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import ApprovalRequired
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDefinition,
)
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from app.agents.capabilities import (
    REGISTRY,
    CapabilityBuildContext,
    CapabilityToolInfo,
    load_builtins,
    register,
)
from app.agents.capabilities.approval import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalGranted,
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
)
from app.agents.deps import AgentDeps
from app.agents.factory import build_agent
from app.agents.model_resolver import ModelRequestSpec, ResolvedCredential
from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_runner import ApprovalChannel
from app.services.approvals import ApprovalService

# Tool names now, not capability ids: the gate matches what the model called,
# so a capability with a write tool and a read tool can gate one of them.
GATED = frozenset({"send_email"})


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _tool_def(capability_id: str | None = "email", name: str = "send_email") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        parameters_json_schema={"type": "object", "properties": {}},
        capability_id=capability_id,
    )


def _call(args: dict[str, Any]) -> ToolCallPart:
    return ToolCallPart(tool_name="send_email", args=args, tool_call_id="call-1")


def _ctx(decision: ApprovalDecision | None) -> MagicMock:
    """A run context whose deps carry an approval channel, or none at all."""
    ctx = MagicMock()
    ctx.deps = AgentDeps(
        run_id=uuid.uuid4(),
        request_approval=None if decision is None else AsyncMock(return_value=decision),
    )
    return ctx


class _Recorder:
    """Stands in for the tool itself, remembering what it was actually run with."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, args: dict[str, Any]) -> str:
        self.calls.append(args)
        return "sent"


class TestGate:
    @pytest.mark.anyio
    async def test_an_approved_call_runs_the_arguments_that_were_approved(self):
        """The model must not be able to change its mind between asking and acting.

        The approval was granted against one recipient; the model proposes
        another on the replay. What runs is the one a person read.
        """
        tool = _Recorder()
        gate = ApprovalGate(required_tool_names=GATED)

        result = await gate.wrap_tool_execute(
            _ctx(ApprovalGranted(tool_args={"to": "approved@example.com"})),
            call=_call({"to": "swapped@example.com"}),
            tool_def=_tool_def(),
            args={"to": "swapped@example.com"},
            handler=tool,
        )

        assert tool.calls == [{"to": "approved@example.com"}]
        assert result == "sent"

    @pytest.mark.anyio
    async def test_a_rejected_call_refuses_without_crashing_the_run(self):
        """A rejection is an answer the agent can relay, not an exception."""
        tool = _Recorder()
        gate = ApprovalGate(required_tool_names=GATED)

        result = await gate.wrap_tool_execute(
            _ctx(ApprovalRejected(note="wrong customer")),
            call=_call({"to": "a@example.com"}),
            tool_def=_tool_def(),
            args={"to": "a@example.com"},
            handler=tool,
        )

        assert tool.calls == []
        assert "wrong customer" in result
        assert "do not call it again" in result

    @pytest.mark.anyio
    async def test_no_approval_channel_refuses_rather_than_proceeding(self):
        """A schedule or webhook cannot ask anyone, so the answer is no.

        Proceeding because nobody was around to object is the exact failure the
        approval queue exists to prevent.
        """
        tool = _Recorder()
        gate = ApprovalGate(required_tool_names=GATED)

        result = await gate.wrap_tool_execute(
            _ctx(None),
            call=_call({"to": "a@example.com"}),
            tool_def=_tool_def(),
            args={"to": "a@example.com"},
            handler=tool,
        )

        assert tool.calls == []
        assert "was not performed" in result

    @pytest.mark.anyio
    async def test_a_pending_decision_parks_the_run(self):
        ctx = _ctx(ApprovalPending())
        gate = ApprovalGate(required_tool_names=GATED)

        with pytest.raises(ApprovalRequired):
            await gate.wrap_tool_execute(
                ctx,
                call=_call({"to": "a@example.com"}),
                tool_def=_tool_def(),
                args={"to": "a@example.com"},
                handler=_Recorder(),
            )

    @pytest.mark.anyio
    async def test_a_tool_that_needs_no_approval_is_untouched(self):
        """Gating everything would make the queue noise nobody reads."""
        tool = _Recorder()
        ctx = _ctx(ApprovalPending())
        gate = ApprovalGate(required_tool_names=GATED)

        result = await gate.wrap_tool_execute(
            ctx,
            call=_call({"query": "refunds"}),
            # Same capability could own it; what decides now is the tool.
            tool_def=_tool_def(name="search_documents"),
            args={"query": "refunds"},
            handler=tool,
        )

        assert tool.calls == [{"query": "refunds"}]
        assert result == "sent"
        ctx.deps.request_approval.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_tool_no_capability_owns_is_untouched(self):
        """An MCP server's tools are governed where the connection is, not here."""
        tool = _Recorder()
        gate = ApprovalGate(required_tool_names=GATED)

        await gate.wrap_tool_execute(
            _ctx(ApprovalPending()),
            call=_call({}),
            tool_def=_tool_def(capability_id=None),
            args={},
            handler=tool,
        )

        assert tool.calls == [{}]


class TestApprovalChannel:
    @pytest.mark.anyio
    async def test_a_first_ask_parks_the_call_and_remembers_which_one(self):
        approval = MagicMock(id=uuid.uuid4())
        approvals = MagicMock(request=AsyncMock(return_value=approval))
        channel = ApprovalChannel(
            approvals=approvals,
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
        )

        decision = await channel(
            ApprovalRequest(
                capability_id="email",
                tool_name="send_email",
                tool_call_id="call-1",
                tool_args={"to": "a@example.com"},
            )
        )

        assert isinstance(decision, ApprovalPending)
        # The approver reads the tool and its arguments, not the capability id.
        assert approvals.request.call_args.kwargs["tool_id"] == "send_email"
        assert approvals.request.call_args.kwargs["tool_args"] == {"to": "a@example.com"}
        assert channel.parked == {str(approval.id): "call-1"}

    @pytest.mark.anyio
    async def test_a_decision_authorises_one_call_only(self):
        """One "yes" must not authorise a loop of the same side effect."""
        approvals = MagicMock(request=AsyncMock(return_value=MagicMock(id=uuid.uuid4())))
        channel = ApprovalChannel(
            approvals=approvals,
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            decided={"call-1": ApprovalGranted(tool_args={"to": "a@example.com"})},
        )
        request = ApprovalRequest(
            capability_id="email",
            tool_name="send_email",
            tool_call_id="call-1",
            tool_args={"to": "a@example.com"},
        )

        first = await channel(request)
        second = await channel(request)

        assert isinstance(first, ApprovalGranted)
        assert isinstance(second, ApprovalPending)
        approvals.request.assert_awaited_once()


class TestApprovalQueue:
    """The service behind the channel: parking a call, and listing what waits."""

    @pytest.mark.anyio
    async def test_parking_a_call_records_everything_an_approver_needs_to_judge_it(self):
        """The asker is an agent mid-run, not a member, so there is no auth context.

        Which run, which agent, which tool and with what arguments therefore have
        to travel as explicit ids — and the arguments especially: approving
        "send_email" without seeing the recipient is a rubber stamp.
        """
        organization_id, run_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        approval = MagicMock(id=uuid.uuid4())
        db = MagicMock(flush=AsyncMock(), refresh=AsyncMock())

        with patch(
            "app.services.approvals.agent_run_repo.create_approval",
            new=AsyncMock(return_value=approval),
        ) as parked:
            requested = await ApprovalService(db).request(
                organization_id=organization_id,
                run_id=run_id,
                agent_id=agent_id,
                tool_id="send_email",
                tool_args={"to": "customer@example.com"},
            )

        assert requested is approval
        assert parked.call_args.kwargs == {
            "organization_id": organization_id,
            "run_id": run_id,
            "agent_id": agent_id,
            "tool_id": "send_email",
            "tool_args": {"to": "customer@example.com"},
        }

    @pytest.mark.anyio
    async def test_the_queue_only_shows_what_is_waiting_in_the_callers_organization(self):
        """One approver deciding another tenant's tool call is the worst version of this feature."""
        ctx = AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OPERATOR
        )
        waiting = MagicMock(id=uuid.uuid4())
        db = MagicMock(flush=AsyncMock(), refresh=AsyncMock())

        with patch(
            "app.services.approvals.agent_run_repo.list_pending_approvals",
            new=AsyncMock(return_value=([waiting], 1)),
        ) as queue:
            pending, total = await ApprovalService(db).list_pending(ctx, skip=10, limit=5)

        assert (pending, total) == ([waiting], 1)
        assert queue.call_args.kwargs == {
            "organization_id": ctx.organization_id,
            "skip": 10,
            "limit": 5,
        }


def _model_spec() -> ModelRequestSpec:
    return ModelRequestSpec(
        profile_id=uuid.uuid4(),
        label="GPT-4.1 (prod)",
        provider="openai",
        model="gpt-4.1",
        params={},
        credential=ResolvedCredential(
            provider="openai", secret=ApiKeySecret(api_key="sk-test-key")
        ),
        fallbacks=[],
    )


GATED_CAPABILITY = "test_gated_action"
GATED_TOOL = "do_the_thing"


@pytest.fixture(autouse=True)
def gated_capability():
    """A capability that exists only to be gated.

    These tests used to borrow whichever real tool was convenient — the clock's,
    as it happened — and then broke the day that capability stopped exposing
    one. What is under test is the gate, not any particular tool, so it gets a
    tool of its own that does nothing and cannot be redesigned out from under
    it.
    """

    @register(
        id=GATED_CAPABILITY,
        name="Gated action",
        category="test",
        description="A side-effecting action that must be approved",
        side_effecting=True,
        tools=(CapabilityToolInfo(id=GATED_TOOL, description="Does the thing."),),
    )
    def _build(ctx: CapabilityBuildContext) -> _GatedAction:
        return _GatedAction()

    yield
    REGISTRY.pop(GATED_CAPABILITY)


@dataclass
class _GatedAction(AbstractCapability[Any]):
    """One tool, no behaviour, so a failure here is always the gate's."""

    def get_toolset(self) -> AbstractToolset[Any]:
        def do_the_thing() -> str:
            """Do the thing that needs a human to say yes first."""
            return "done"

        toolset: FunctionToolset[Any] = FunctionToolset()
        toolset.add_function(do_the_thing, takes_ctx=False)
        return toolset


def _clock_caller() -> FunctionModel:
    """A model that calls the gated tool once, then answers."""

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        answered = any(isinstance(part, ToolReturnPart) for m in messages for part in m.parts)
        if answered:
            return ModelResponse(parts=[TextPart("It is time.")])
        return ModelResponse(
            parts=[ToolCallPart(tool_name=GATED_TOOL, args={}, tool_call_id="call-1")]
        )

    return FunctionModel(respond)


def _gated_agent(channel: ApprovalChannel):
    """An agent whose one tool the spec marks as needing a human."""
    spec = AgentSpec(name="Clerk", capabilities=[{"id": GATED_CAPABILITY, "approval": "required"}])
    return build_agent(
        spec,
        _model_spec(),
        organization_id=uuid.uuid4(),
        run_id=channel.run_id,
        request_approval=channel,
    )


class TestParkAndResume:
    """The round trip the feature exists for, through a real agent."""

    def _channel(self, run_id: uuid.UUID, **kwargs: Any) -> ApprovalChannel:
        return ApprovalChannel(
            approvals=MagicMock(request=AsyncMock(return_value=MagicMock(id=uuid.uuid4()))),
            organization_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            run_id=run_id,
            **kwargs,
        )

    @pytest.mark.anyio
    async def test_a_parked_run_ends_with_the_call_waiting_and_then_continues(self):
        """Park, decide, resume — and the tool runs exactly once, on approval."""
        run_id = uuid.uuid4()
        parking = self._channel(run_id)
        built = _gated_agent(parking)

        with built.agent.override(model=_clock_caller()):
            parked = await built.agent.run("what time is it", deps=built.deps)

        assert isinstance(parked.output, DeferredToolRequests)
        assert [call.tool_name for call in parked.output.approvals] == [GATED_TOOL]
        assert list(parking.parked.values()) == ["call-1"]

        resuming = self._channel(run_id, decided={"call-1": ApprovalGranted(tool_args={})})
        resumed_build = _gated_agent(resuming)

        with resumed_build.agent.override(model=_clock_caller()):
            resumed = await resumed_build.agent.run(
                deps=resumed_build.deps,
                message_history=parked.all_messages(),
                deferred_tool_results=DeferredToolResults(
                    approvals={"call-1": ToolApproved(override_args={})}
                ),
            )

        assert resumed.output == "It is time."

    @pytest.mark.anyio
    async def test_a_rejected_call_lets_the_agent_answer_anyway(self):
        """The run must survive a "no" — the user still deserves a reply."""
        run_id = uuid.uuid4()
        parking = self._channel(run_id)
        built = _gated_agent(parking)

        with built.agent.override(model=_clock_caller()):
            parked = await built.agent.run("what time is it", deps=built.deps)

        resuming = self._channel(run_id, decided={"call-1": ApprovalRejected(note="not now")})
        resumed_build = _gated_agent(resuming)

        with resumed_build.agent.override(model=_clock_caller()):
            resumed = await resumed_build.agent.run(
                deps=resumed_build.deps,
                message_history=parked.all_messages(),
                deferred_tool_results=DeferredToolResults(
                    approvals={"call-1": ToolApproved(override_args={})}
                ),
            )

        assert resumed.output == "It is time."
        refusals = [
            part.content
            for message in resumed.all_messages()
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        assert any("not now" in str(content) for content in refusals)
