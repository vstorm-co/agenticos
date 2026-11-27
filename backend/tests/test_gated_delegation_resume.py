"""A delegation that itself needs approval, whose delegate then needs one too.

Approving the delegation (`task`) let the delegate run until its own gated tool
parked the run. Approving that tool resumed the run, and the replay reached the
parent's `task` call again - through the gate, with no decision for it, because
the run's decisions are only the ones for its latest park. So it parked on the
delegation once more, the delegate's place was not kept, and approving the
delegation again started the delegate over to ask for its tool again: a loop that
ran for as long as somebody kept approving.

`ApprovalChannel.continuing` names the `task` calls a resume continues: each one
already passed its gate, since its delegate ran and parked inside it. These drive
the real capability, the real gate and the runner's real verdict split through
every park until the run answers, one level down and two.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.tools import DeferredToolRequests

from app.agents.capabilities.approval import (
    ApprovalGate,
    ApprovalGranted,
    ApprovalPending,
    ApprovalRequest,
)
from app.agents.deps import AgentDeps
from app.agents.subagent_runtime import DelegationStash, ResolvedSubagent
from app.services.agent_runner import ApprovalChannel, _resume_plan
from tests.test_subagent_nested_resume import (
    GATED_TOOL,
    MIDDLE,
    SPECIALIST,
    _answer,
    _capability,
    _delegating_model,
    _parked_state,
    _Queue,
    _resolved,
    _specialist_delegate,
    _to_register,
    _verdicts,
    _write_approvals,
)

pytestmark = pytest.mark.anyio

DELEGATION_TOOL = "task"


def _gating_delegation() -> ApprovalGate:
    """What an agent whose `task` asks first is built with."""
    return ApprovalGate(required_tool_names=frozenset({DELEGATION_TOOL}))


def _gated_middle(*, calls: list[dict[str, Any]], stash: DelegationStash) -> ResolvedSubagent:
    """A delegate whose own delegation asks first, above a specialist whose tool does."""

    def build_it() -> PydanticAgent[Any, Any]:
        return PydanticAgent(
            _delegating_model("edited", SPECIALIST),
            output_type=[str, DeferredToolRequests],
            capabilities=[
                _gating_delegation(),
                _capability(_specialist_delegate(gated=True, calls=calls), stash=stash, depth=1),
            ],
        )

    return _resolved(MIDDLE, build_it)


@dataclass
class _Run:
    """Every park of one run, decided as somebody approving each card would."""

    asked: list[tuple[str, str | None]] = field(default_factory=list)
    """`(tool, delegate)` per approval card, in the order they were shown."""


async def _approve_until_it_answers(
    delegate: Any, *, continuing: bool = True, most: int = 6
) -> tuple[Any, _Run]:
    """Start a run whose `task` asks first and approve every park until it answers.

    Each resume is assembled as `resume` assembles one: a fresh tree, the stash
    loaded from the park, this park's verdicts in `decided` and every delegation
    it parked inside in `continuing`. `delegate(stash)` builds the run's delegate
    again for each turn, as the runner rebuilds it from the parked version.
    """
    run = _Run()
    stash = DelegationStash()
    channel = ApprovalChannel(organization_id=uuid4(), agent_id=uuid4(), run_id=uuid4())
    agent = PydanticAgent(
        _delegating_model("answer", delegate(stash).name),
        output_type=[str, DeferredToolRequests],
        capabilities=[_gating_delegation(), _capability(delegate(stash), stash=stash)],
    )
    result = await agent.run(
        "what is the weather in Krakow",
        deps=AgentDeps(organization_id=uuid4(), run_id=uuid4(), request_approval=channel),
    )
    for _ in range(most):
        if not isinstance(result.output, DeferredToolRequests):
            return result, run
        queue = _Queue()
        await _write_approvals(channel, queue)
        state = _parked_state(result, channel=channel, stash=stash)
        run.asked += [
            (row.tool_id, row.subagent_name)
            for row in queue.rows
            if str(row.id) in state.tool_call_ids
        ]
        queue.decide(approved=True)
        decided, approved_args = _verdicts(state, queue)
        plan = _resume_plan(state, approved_args)
        stash = DelegationStash(
            resuming=plan.delegations,
            spent=plan.spent,
            started=plan.started,
            to_register=_to_register(state, plan),
        )
        channel = ApprovalChannel(
            organization_id=uuid4(),
            agent_id=uuid4(),
            run_id=uuid4(),
            decided=decided,
            continuing=set(plan.started) if continuing else set(),
        )
        agent = PydanticAgent(
            _delegating_model("answer", delegate(stash).name),
            output_type=[str, DeferredToolRequests],
            capabilities=[_gating_delegation(), _capability(delegate(stash), stash=stash)],
        )
        result = await agent.run(
            None,
            deps=AgentDeps(organization_id=uuid4(), run_id=uuid4(), request_approval=channel),
            message_history=ModelMessagesTypeAdapter.validate_python(state.messages),
            deferred_tool_results=plan.results,
        )
    return result, run


class TestAnApprovedDelegationIsNotAskedAgain:
    async def test_one_decision_each_then_the_answer(self):
        """The delegation once, the delegate's tool once, then the run answers."""
        calls: list[dict[str, Any]] = []

        result, run = await _approve_until_it_answers(
            lambda _stash: _specialist_delegate(gated=True, calls=calls)
        )

        assert not isinstance(result.output, DeferredToolRequests), run.asked
        assert run.asked == [(DELEGATION_TOOL, None), (GATED_TOOL, SPECIALIST)]
        assert "21C and clear" in _answer(result)
        # Continued, not started over: the approved tool ran once.
        assert calls == [{"city": "Krakow"}]

    async def test_without_the_continued_delegations_it_asks_for_ever(self):
        """The loop this fixes, pinned so the reason for `continuing` stays visible."""
        calls: list[dict[str, Any]] = []

        result, run = await _approve_until_it_answers(
            lambda _stash: _specialist_delegate(gated=True, calls=calls),
            continuing=False,
            most=4,
        )

        assert isinstance(result.output, DeferredToolRequests)
        assert run.asked == [
            (DELEGATION_TOOL, None),
            (GATED_TOOL, SPECIALIST),
            (DELEGATION_TOOL, None),
            (GATED_TOOL, SPECIALIST),
        ]

    async def test_two_levels_down_each_delegation_is_asked_once(self):
        """A delegate's own gated delegation is continued too, not only the run's."""
        calls: list[dict[str, Any]] = []

        result, run = await _approve_until_it_answers(
            lambda stash: _gated_middle(calls=calls, stash=stash)
        )

        assert not isinstance(result.output, DeferredToolRequests), run.asked
        assert run.asked == [
            (DELEGATION_TOOL, None),
            (DELEGATION_TOOL, MIDDLE),
            (GATED_TOOL, SPECIALIST),
        ]
        assert "21C and clear" in _answer(result)
        assert calls == [{"city": "Krakow"}]


class TestTheChannelContinuesOnlyWhatItWasTold:
    @staticmethod
    def _asking(tool_call_id: str) -> ApprovalRequest:
        return ApprovalRequest(
            capability_id="subagents",
            tool_name=DELEGATION_TOOL,
            tool_call_id=tool_call_id,
            tool_args={"subagent_type": SPECIALIST, "description": "the weather in Krakow"},
        )

    async def test_a_continued_delegation_runs_with_its_own_arguments_once(self):
        channel = ApprovalChannel(
            organization_id=uuid4(), agent_id=uuid4(), run_id=uuid4(), continuing={"call-1"}
        )

        first = await channel(self._asking("call-1"))
        again = await channel(self._asking("call-1"))

        assert first == ApprovalGranted(self._asking("call-1").tool_args)
        # A second call under the same id is a new act and parks like any other.
        assert isinstance(again, ApprovalPending)
        assert [parked.tool_call_id for parked in channel.requested] == ["call-1"]

    async def test_another_call_is_not_continued(self):
        channel = ApprovalChannel(
            organization_id=uuid4(), agent_id=uuid4(), run_id=uuid4(), continuing={"call-1"}
        )

        assert isinstance(await channel(self._asking("call-2")), ApprovalPending)
        assert channel.continuing == {"call-1"}
