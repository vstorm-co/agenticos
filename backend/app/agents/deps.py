"""Dependencies handed to every tool call.

`AgentDeps` is the only channel through which a tool learns anything the model
did not tell it: which collections the agent may search, what the tool was
configured with, who is asking. That separation is the security boundary - a
tool's *parameters* are model-controlled and therefore untrusted, while its
*deps* are resolved server-side from the agent spec and the request.

The practical rule when adding a tool: if the model should not be able to choose
it, it belongs here, not in the signature.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.agents.approval import ApprovalDecision, ApprovalRequest
from app.agents.subagent_events import SubagentEventSink

AskUserCallback = Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]]]
ApprovalCallback = Callable[[ApprovalRequest], Awaitable[ApprovalDecision]]


@dataclass
class AgentDeps:
    """Everything a tool may need that the model must not control."""

    organization_id: UUID | None = None
    user_id: str | None = None
    user_name: str | None = None
    agent_id: UUID | None = None
    run_id: UUID | None = None

    # Collection names this agent may search, resolved from its bindings.
    kb_collection_names: list[str] = field(default_factory=list)

    # Set when the surface can ask the user something mid-run (WebSocket chat);
    # None on surfaces that cannot, so tools must handle its absence.
    ask_user: AskUserCallback | None = None

    # Set when the surface can hold a run for human approval. A tool that needs
    # approval and finds this None must refuse rather than proceed unattended.
    request_approval: ApprovalCallback | None = None

    # Set when the surface can show a delegation while it is happening; None
    # everywhere else, so the delegation still runs and simply is not narrated.
    subagent_events: SubagentEventSink | None = None

    # How much further this run may delegate. Zero - the default - is an agent
    # that cannot delegate at all, which is every agent whose spec does not bind
    # the `subagents` capability.
    delegation_depth_remaining: int = 0

    metadata: dict[str, Any] = field(default_factory=dict)

    def clone_for_subagent(self, max_depth: int = 0) -> AgentDeps:
        """The deps a delegated run gets.

        Required by `subagents_pydantic_ai.SubAgentDepsProtocol`, which calls it
        for every delegation with one less than the parent's nesting budget. A
        fresh instance rather than `self`, as the protocol demands: concurrent
        specialists sharing one object would share whatever a tool wrote onto it.

        What a delegate **inherits**, and why each is deliberate:

        `organization_id` and `user_id` - a delegation is not a privilege
        boundary. The publisher's `AGENTS_RUN` on every delegate was checked when
        the parent was published; at run time a delegate acts for the same person,
        in the same organization, exactly as a bound collection or MCP connection
        does.

        `agent_id` and `run_id` - the *parent's*, unchanged, and this is the one
        that looks like a bug and is not. They key the workspace session, so
        keeping them is what lets a researcher write `/workspace/notes.md` and a
        writer read it. A delegate with a private filesystem is a delegate whose
        work nobody can use, and every intermediate result would have to come
        back through the parent's context - which is most of what a fan-out is
        supposed to save. A delegation's *own* run row records its identity; deps
        are about what its tools can reach.

        `ask_user` and `request_approval` - the parent's channels. A specialist
        that needs a person needs the person who is already waiting.

        `subagent_events` - so a specialist's own delegation still narrates,
        one `depth` further in.

        What it does **not** inherit: `kb_collection_names`. Those come from the
        delegate's own spec, resolved by the runner when it builds the delegate,
        and inheriting the parent's would hand a specialist a collection nobody
        granted it.
        """
        return AgentDeps(
            organization_id=self.organization_id,
            user_id=self.user_id,
            user_name=self.user_name,
            agent_id=self.agent_id,
            run_id=self.run_id,
            ask_user=self.ask_user,
            request_approval=self.request_approval,
            subagent_events=self.subagent_events,
            # Floored at zero rather than passed through: the library documents
            # that it threads this number without enforcing it, and a negative
            # budget arriving from `max_nesting_depth - 1` would read as "some
            # depth remaining" to anything doing a truthiness check.
            delegation_depth_remaining=max(max_depth, 0),
            metadata=dict(self.metadata),
        )
