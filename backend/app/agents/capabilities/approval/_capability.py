"""Holding a side-effecting tool call until a human says yes.

The gate wraps *tool execution* rather than living inside a tool, for the same
reason the budget guard wraps model requests: enforcement that a tool has to
remember to call is enforcement that a new tool will forget. Wrapping means a
capability marked side-effecting is gated whether or not its author thought
about approval.

Three rules the rest of the design follows from:

*The approved arguments are what runs.* A decision is granted against the
arguments a person read. On the replay the gate executes those, not whatever the
model proposes the second time round, so the model cannot change its mind
between asking and acting.

*No channel means no.* An agent running somewhere nobody can be asked - a
schedule, a webhook - refuses the call and says so. Proceeding unattended is the
exact failure the approval queue exists to prevent.

*A refusal is an answer, not a crash.* Both a rejection and a missing channel
come back to the model as tool output, so it can tell the user what did not
happen instead of the run dying with a stack trace.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ApprovalRequired, RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from app.agents.approval import (
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
    refusal,
)
from app.agents.capabilities._registry import FRAMEWORK_TOOL_NAMES
from app.agents.deps import AgentDeps
from app.agents.mcp import NEEDS_APPROVAL

logger = logging.getLogger(__name__)


@dataclass
class ApprovalGate(AbstractCapability[AgentDeps]):
    """Stops a tool that needs a human from running before one has answered.

    Gating is per *tool*. A capability is the unit you switch on - "this agent
    may work with files" - but it is not the unit you approve: writing a file
    and reading one are two decisions, and a queue that asks about both is a
    queue people learn to click through. Which names land here is resolved once
    from the spec, in :func:`app.agents.capabilities.approval.tool_needs_approval`.

    Tools that no capability owns - an MCP server's - are not gated by name,
    even if one happens to share a name with a gated tool. Their approval is a
    property of the binding: `ApprovalMarked` marks each one from the binding's
    policy and the server's read-only hint, and the mark is what is read here.

    `gate_every_tool` is the one thing that overrides both of those, and it comes
    from a person rather than from a spec: `ApprovalMode.ASK_ALL` on a chat
    session asks about everything the agent can reach, MCP tools included (#925).
    It only ever tightens - a tool the spec gated stays gated - so it needs no
    permission and no ceiling, and it is the honest answer to "I do not trust this
    agent yet". Guessing is not the risk in that direction: being asked about a
    read is a nuisance, where not being asked about a write is the failure the
    queue exists for.
    """

    required_tool_names: frozenset[str] = frozenset()
    gate_every_tool: bool = False
    # Tools that are themselves a question to the person there - `connect_account`
    # acts on nothing and only waits for them. Gated, even under `ASK_ALL`, they
    # would ask them to approve being asked, and a parked call resumes where
    # nobody can be asked. Named by the factory for the tools it attached, never
    # read off tool metadata, which an MCP server writes.
    asking_tool_names: frozenset[str] = frozenset()

    async def wrap_tool_execute(
        self,
        ctx: RunContext[AgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        handler: WrapToolExecuteHandler,
    ) -> Any:
        """Ask before executing, and execute only what was asked about."""
        capability_id = tool_def.capability_id
        # A capability id is what tells this deployment's tool from an MCP
        # server's, whose approval is a different question - except for the
        # framework's own, which carries no capability id and is still ours to
        # gate: `load_capability` is how a skill is opened, so a spec that asked
        # for approval before a skill is loaded has nowhere else to put it
        # (#1704 review).
        # An MCP server's tool carries its binding's verdict, set by
        # `ApprovalMarked` from the binding's policy and the server's read-only
        # hint (#2060) - only for a tool no capability owns, so a capability's
        # tool cannot be released by metadata.
        marked = capability_id is None and (tool_def.metadata or {}).get(NEEDS_APPROVAL) is True
        gated = tool_def.name not in self.asking_tool_names and (
            self.gate_every_tool
            or marked
            or (
                tool_def.name in self.required_tool_names
                and (capability_id is not None or tool_def.name in FRAMEWORK_TOOL_NAMES)
            )
        )
        if not gated:
            return await handler(args)

        ask = ctx.deps.request_approval
        if ask is None:
            logger.warning(
                "Tool %s needs approval but run %s has no approval channel",
                tool_def.name,
                ctx.deps.run_id,
            )
            return refusal(tool_def.name, "this surface cannot ask anyone to approve it")

        decision = await ask(
            ApprovalRequest(
                capability_id=capability_id,
                tool_name=tool_def.name,
                tool_call_id=call.tool_call_id,
                tool_args=args,
            )
        )
        if isinstance(decision, ApprovalPending):
            # Ends the run with the parked call recorded against it, rather than
            # holding a coroutine open for however long a person takes.
            raise ApprovalRequired()
        if isinstance(decision, ApprovalRejected):
            return refusal(tool_def.name, decision.note or "a reviewer rejected it")
        return await handler(decision.tool_args)
