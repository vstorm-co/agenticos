"""The one tool call that starts a delegation, and what this platform does around it.

The delegation tools themselves come from `subagents-pydantic-ai`, so there is no
toolset written here - this is the `sandbox` arrangement, where the library owns
the implementation and this repository owns everything the platform decides. Three
things are decided, and all three have to happen around the *call* rather than
inside the library:

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

Only `task` is intercepted, because only `task` is offered - `create_agent` and
`delegate` are declared but not wired (see the README). Wiring them means routing
them through here too: a delegation this module does not see is one that escapes
all three decisions above.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


@dataclass
class DelegatingToolset(WrapperToolset[AgentDeps]):
    """The library's delegation tools, with the platform's decisions around `task`."""

    journal: DelegationJournal

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[AgentDeps],
        tool: ToolsetTool[AgentDeps],
    ) -> Any:
        """Run a delegation tool, and account for the one that delegates.

        The other six pass straight through. They read and steer tasks this run
        already started, so there is nothing to decide about them that the
        approval gate does not already decide.
        """
        if name != TASK_TOOL:
            return await self.wrapped.call_tool(name, tool_args, ctx, tool)

        sink = ctx.deps.subagent_events
        # Before the ceiling is checked, so a background delegation that has
        # finished stops occupying a slot - and so its outcome is recorded near
        # the moment it happened rather than at the end of the run.
        await self.journal.settle_background(sink)
        if self.journal.in_flight() >= self.journal.max_fanout:
            return self.journal.refusal()

        name_asked = str(tool_args.get("subagent_type", ""))
        delegation = self.journal.begin(
            delegate=self.journal.runtime.named(name_asked),
            name=name_asked,
            prompt=str(tool_args.get("description", "")),
            tool_args=tool_args,
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
        finally:
            # In a `finally` because a delegation that failed is still a
            # delegation: the library raises `ModelRetry` for one it could not
            # contain and `UsageLimitExceeded` for one that ran out of steps, and
            # both spent money that has to be attributed before it is re-raised.
            await self.journal.close(delegation, sink)
