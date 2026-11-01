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

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from pydantic_ai import ApprovalRequired, RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapToolExecuteHandler
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_core import to_jsonable_python

from app.agents.approval import (
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
    refusal,
)
from app.agents.capabilities._registry import FRAMEWORK_TOOL_NAMES, ApprovalDescriber
from app.agents.deps import AgentDeps
from app.agents.mcp import ACCOUNT, NEEDS_APPROVAL

logger = logging.getLogger(__name__)

# How long a describer may take before the call is parked without its context.
# Its queries are a few primary-key reads; a database slow enough to miss this is
# one the approval must not wait on.
DESCRIBE_TIMEOUT_SECONDS = 5.0


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
    # Effective tool name to the capability's describer for it, resolved from the
    # spec by `approval_describers` - a renamed tool keeps its describer.
    describers: Mapping[str, ApprovalDescriber] = field(default_factory=dict)
    # Effective tool name to the stable id its capability declares it under, from
    # `approval_tool_ids`, so the request names the tool the way a surface words it.
    tool_ids: Mapping[str, str] = field(default_factory=dict)

    @staticmethod
    async def _describe(
        ctx: RunContext[AgentDeps],
        tool_def: ToolDefinition,
        describe: ApprovalDescriber,
        args: dict[str, Any],
    ) -> dict[str, str] | None:
        """The call's ids as names for the person deciding, or `None`.

        Never raises: a description is a courtesy on the card, and a failure here
        must not stop the call from being asked about - a call nobody can be asked
        about is refused, which would make a broken lookup a broken tool.
        """
        try:
            async with asyncio.timeout(DESCRIBE_TIMEOUT_SECONDS):
                described = await describe(ctx.deps, args)
        except Exception:
            logger.warning(
                "Could not describe %s for approval on run %s; parking it without context",
                tool_def.name,
                ctx.deps.run_id,
                exc_info=True,
            )
            return None
        return described or None

    def gates(self, tool_def: ToolDefinition) -> bool:
        """Whether a call to this tool waits for a person's decision."""
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
        capability_id = tool_def.capability_id
        marked = capability_id is None and (tool_def.metadata or {}).get(NEEDS_APPROVAL) is True
        return tool_def.name not in self.asking_tool_names and (
            self.gate_every_tool
            or marked
            or (
                tool_def.name in self.required_tool_names
                and (capability_id is not None or tool_def.name in FRAMEWORK_TOOL_NAMES)
            )
        )

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
        if not self.gates(tool_def):
            return await handler(args)

        ask = ctx.deps.request_approval
        if ask is None:
            logger.warning(
                "Tool %s needs approval but run %s has no approval channel",
                tool_def.name,
                ctx.deps.run_id,
            )
            return refusal(tool_def.name, "this surface cannot ask anyone to approve it")

        # As JSON, which is how the queue stores them and a person reads them: a tool
        # taking a `UUID` - every table write - otherwise failed to be
        # asked about at all.
        asked = to_jsonable_python(args)
        # Only a capability's own tool is named or described, so an MCP tool sharing
        # a name with one under `ASK_ALL` is never handed a describer written for
        # another tool.
        owned = capability_id is not None
        describer = self.describers.get(tool_def.name) if owned else None
        decision = await ask(
            ApprovalRequest(
                capability_id=capability_id,
                tool_name=tool_def.name,
                tool_call_id=call.tool_call_id,
                tool_args=asked,
                # Only an MCP tool's, for the reason `marked` is: no capability
                # tool can be given an account by metadata.
                account=(tool_def.metadata or {}).get(ACCOUNT) if capability_id is None else None,
                capability_tool_id=self.tool_ids.get(tool_def.name) if owned else None,
                # Handed over unawaited: the channel runs it only for a call it is
                # about to record, never for one a resumed run already decided.
                describe=(
                    None
                    if describer is None
                    else partial(self._describe, ctx, tool_def, describer, args)
                ),
            )
        )
        if isinstance(decision, ApprovalPending):
            # Ends the run with the parked call recorded against it, rather than
            # holding a coroutine open for however long a person takes.
            raise ApprovalRequired()
        if isinstance(decision, ApprovalRejected):
            return refusal(tool_def.name, decision.note or "a reviewer rejected it")
        # The arguments approved are what runs. When they are this call's own, run
        # them as the tool validated them, so an id is a `UUID` again and not its text.
        approved = decision.tool_args
        return await handler(args if approved == asked else approved)
