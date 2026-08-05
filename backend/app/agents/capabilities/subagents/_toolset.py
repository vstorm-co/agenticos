"""The tool calls that start a delegation, and what this platform does around them.

The delegation tools themselves come from `subagents-pydantic-ai`, so there is no
toolset written here - this is the `sandbox` arrangement, where the library owns
the implementation and this repository owns everything the platform decides. Seven
things are decided, and every one of them has to happen around the *call* rather
than inside the library:

*The mode is the spec's, not the model's.* The library's `task` tool takes a
`mode` argument whose default is `"sync"`, which makes "the model chose" and "the
model said nothing" indistinguishable. So the argument is replaced on the way
through with the mode the agent's author configured.

*Fan-out is refused, readably.* A run that may launch background delegations can
otherwise keep launching them, and ten agents against one budget is a cost
multiplier nobody chose. The refusal comes back as a tool result the model can
act on, not as an exception that ends the run.

*Every delegation is recorded.* The library reports a delegation's result to the
model and its status on a task handle; neither is a run row, and neither says
what it cost. What the run's shared ledger grew by while the delegation ran is
that number, and this is the only place both ends of that window exist.

*A delegate that stopped for a person keeps its place.* The suspension arrives
here as a `CallDeferred` or an `ApprovalRequired` propagating out of the wrapped
call, on its way to park the parent's own tool call - and this is the only point
at which the delegation record, the library's task handle and the parent's tool
call id all exist at once. So the delegate's position is stashed on the way past
and the exception is re-raised unchanged. Letting it through without stashing is
what made the granted approval and the replayed run disagree: see
:meth:`~app.agents.capabilities.subagents._journal.DelegationJournal.park`.

*A specialist a model invents names its model, gets no capabilities, and cannot
take a delegate's name.* Three decisions about `create_agent` and `delegate`,
here rather than in the library's own validation because the library validates
what it was configured with and none of these three is expressible that way. See
:meth:`DelegatingToolset._refuse_dynamic`.

*A specialist never asks the parent a question.* Which is a decision about the
arguments rather than about the call, so it is applied to them on the way past:
see :func:`_autonomously`.

Three entry points therefore reach a delegation - `task`, `delegate`, and `task`
addressing something `create_agent` registered - and all three come through here.
A delegation this module does not see is one that escapes every decision above,
which is why :data:`_ENTRY_POINTS` is a table rather than a comparison against
one name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.exceptions import ApprovalRequired, CallDeferred
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import ToolsetTool, WrapperToolset

from app.agents.capabilities.subagents._journal import DelegationJournal
from app.agents.deps import AgentDeps

TASK_TOOL = "task"
"""The library's delegation entry point, under the id this repository declares it.

A binding may rename it for its own model, and by the time a call reaches here it
has been renamed back: `CapabilityDef.effective_tools` and the registry's
override wrapper sit outside this one, so what arrives is always the stable id.
"""

DELEGATE_TOOL = "delegate"
"""Create a specialist and delegate to it in one call."""

CREATE_AGENT_TOOL = "create_agent"
"""Create a specialist and keep it for as long as this reply lasts.

Not a delegation - nothing runs - so it is checked and passed through rather than
recorded. What it registers is reached through `task`, which is a delegation and
is accounted for as one.
"""


@dataclass(frozen=True)
class _EntryPoint:
    """Where one tool's arguments name the delegate and the work.

    A table rather than a comparison against `task`, because `delegate` spells
    both differently and is otherwise a delegation in every respect. Reading the
    two names off the entry point is what stopped the mode, the fan-out ceiling
    and the recording from applying to one door and not the other.
    """

    delegate: str
    """The argument naming who the work goes to."""

    prompt: str
    """The argument carrying the work itself."""

    dynamic: bool
    """Whether this call also invents the specialist, and so needs its checks."""


_ENTRY_POINTS: dict[str, _EntryPoint] = {
    TASK_TOOL: _EntryPoint(delegate="subagent_type", prompt="description", dynamic=False),
    DELEGATE_TOOL: _EntryPoint(delegate="name", prompt="description", dynamic=True),
}


@dataclass
class DelegatingToolset(WrapperToolset[AgentDeps]):
    """The library's delegation tools, with the platform's decisions around them."""

    journal: DelegationJournal

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDeps],
        tool: ToolsetTool[AgentDeps],
    ) -> Any:
        """Run a delegation tool, and account for the ones that delegate.

        The lifecycle tools pass straight through. They read and steer tasks this
        run already started, so there is nothing to decide about them that the
        approval gate does not already decide.
        """
        if name == CREATE_AGENT_TOOL:
            refusal = self._refuse_dynamic(tool_args, named=str(tool_args.get("name", "")))
            if refusal is not None:
                return refusal
            return await self.wrapped.call_tool(name, _autonomously(tool_args), ctx, tool)

        entry = _ENTRY_POINTS.get(name)
        if entry is None:
            return await self.wrapped.call_tool(name, tool_args, ctx, tool)
        return await self._delegate(entry, name, tool_args, ctx, tool)

    async def _delegate(
        self,
        entry: _EntryPoint,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDeps],
        tool: ToolsetTool[AgentDeps],
    ) -> Any:
        """One delegation, whichever entry point the model reached it through."""
        name_asked = str(tool_args.get(entry.delegate, ""))
        if entry.dynamic:
            refusal = self._refuse_dynamic(tool_args, named=name_asked)
            if refusal is not None:
                return refusal
            tool_args = _autonomously(tool_args)

        sink = ctx.deps.subagent_events
        # Before the ceiling is checked, so a background delegation that has
        # finished stops occupying a slot - and so its outcome is recorded near
        # the moment it happened rather than at the end of the run.
        await self.journal.settle_background(sink)
        if self.journal.in_flight() >= self.journal.max_fanout:
            return self.journal.refusal()

        delegation = self.journal.begin(
            # `None` for a specialist the model invented, exactly as for a name it
            # made up: neither has a resolved entry, so neither has an agent row
            # to attribute a run to and neither carries a preferred mode.
            delegate=self.journal.runtime.named(name_asked),
            name=name_asked,
            prompt=str(tool_args.get(entry.prompt, "")),
            tool_args=tool_args,
            # What identifies this delegation across a park and a resume. The
            # replayed run presents the same call, which is how the stand-in agent
            # knows to continue the delegate rather than start it again.
            tool_call_id=ctx.tool_call_id,
        )
        try:
            with self.journal.delegating(delegation):
                # A copy rather than a mutation: the original dict is what the
                # transcript and the approval gate were handed, and rewriting it
                # underneath them would make the recorded call disagree with the
                # one that was authorised.
                return await self.wrapped.call_tool(
                    name, {**tool_args, "mode": delegation.mode}, ctx, tool
                )
        except (ApprovalRequired, CallDeferred):
            # A delegate that stopped for a person, on its way to parking the
            # parent's own call. Stashed and re-raised unchanged: the signal is how
            # Pydantic AI suspends a run, and swallowing it would report unfinished
            # work as an answer. Only these two - a delegation that failed is
            # settled by the `finally` below, and a `SkipTool*` signal never
            # reaches a delegate's own tools.
            self.journal.park(delegation)
            raise
        finally:
            # In a `finally` because a delegation that failed is still a
            # delegation: the library raises `ModelRetry` for one it could not
            # contain and `UsageLimitExceeded` for one that ran out of steps, and
            # both spent money that has to be attributed before it is re-raised.
            await self.journal.close(delegation, sink)

    def _refuse_dynamic(self, tool_args: dict[str, Any], *, named: str) -> str | None:
        """What a specialist a model invented is refused for, or `None` to go ahead.

        Three rules, each a tool result the model can act on rather than an
        exception - the same reasoning as the fan-out ceiling: none is a fault, all
        three are the model being told what this deployment allows.

        One more rule is the library's and is deliberately left to it: a model
        *outside* `allowed_models` is refused by name, against the list the runner
        resolved from the organization's own profiles, with the alternatives in the
        message. That check is right, so it is not repeated here.

        *A specialist must name its model.* The library would fall back on
        `SubAgentCapability.default_model`, and this platform has no default model
        anywhere - publish validation refuses an agent that does not name one,
        because a model an agent did not choose is one somebody else's change can
        swap underneath it. Refused here rather than by giving the library an
        unusable `default_model`, because a tool result naming what this deployment
        allows is something the model can act on and an exception raised from inside
        the library is not. The list is not repeated in the message because the
        instructions carry it and `ReinjectSystemPrompt` keeps it there.

        *A specialist gets no capabilities.* Letting a model grant its own child a
        capability is the ungranted-scope failure wearing a new hat, so
        `capabilities_map` is never passed - which makes the library's own
        `validate_capabilities` a no-op and leaves only
        `validate_capabilities_with_factory`, whose message tells the model to
        configure a factory it cannot reach. Refused here so the answer is about
        what the deployment allows.

        *A specialist cannot answer to a name this agent already delegates to.* The
        library checks only its own registry, so one called `researcher` beside a
        pinned delegate of that slug is accepted - and then every `task` call
        reaches the *delegate*, because `SubAgentToolset` matches the configured
        ones first. The model would be addressing an agent somebody else published
        while believing it wrote the instructions, and nothing would say so.
        """
        if not tool_args.get("model"):
            return (
                "Refused: say which model this specialist runs on. This deployment has "
                "no default model - use one of the models listed under Delegation in "
                "your instructions, exactly as written there."
            )
        if tool_args.get("capabilities"):
            return (
                "Refused: a specialist you define gets no capabilities - no knowledge, "
                "no tools, no delegates of its own. Give it instructions and a model, "
                "and keep work that needs a tool here or with one of the specialists "
                "this agent was given."
            )
        if self.journal.runtime.named(named) is not None:
            return (
                f"Refused: '{named}' is already one of this agent's specialists, and two "
                "answering to one name leaves no way to say which you meant. Delegate to "
                "it with the task tool, or choose another name."
            )
        return None


def _autonomously(tool_args: dict[str, Any]) -> dict[str, Any]:
    """The same call, with the specialist's licence to ask the parent revoked.

    The library injects an `ask_parent` toolset into every agent it built itself,
    which a dynamic specialist is - and `can_ask_questions` is a *model-supplied*
    argument defaulting to `True`, so the model decides. This platform has already
    decided, for every delegate: a specialist works autonomously and says so if it
    could not, and one that needs a person reaches one through its own
    capabilities, on the parent's channels.

    Left at the model's discretion the tool would not merely be useless, it would
    work: `ask_parent` falls back to `ctx.deps.ask_user`, which
    `clone_for_subagent` passes down - so a specialist whose instructions a model
    wrote a moment ago would put a question directly to the person waiting on the
    parent, wearing that model's own name for it.

    A copy rather than a mutation, for the reason the mode is copied: the original
    dict is what the transcript and the approval gate were handed.
    """
    return {**tool_args, "can_ask_questions": False}
