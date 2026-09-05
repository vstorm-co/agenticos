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
from app.agents.compaction_events import CompactionEvent
from app.agents.subagent_events import SubagentEventSink

AskUserCallback = Callable[[str, list[str]], Awaitable[str]]
"""How a delegate reaches the person waiting on its parent, and back.

One question in, one answer out, which is the shape `subagents_pydantic_ai`'s
`ask_parent` tool calls `ctx.deps.ask_user` with - this field exists to feed that
tool and nothing here calls it otherwise. A surface that batches its elicitation
(the WebSocket asks a whole list at once) adapts that to this one-question shape at
its edge; a surface that cannot hold a question open leaves it `None`, and a
delegate that would ask is told a person could not be reached.
"""

ApprovalCallback = Callable[[ApprovalRequest], Awaitable[ApprovalDecision]]

CompactionSink = Callable[[CompactionEvent], Awaitable[None]]
"""Where a surface hears that the history is being summarised, and that it is done.

Only the summarising strategy reaches for this. The zero-LLM ones edit a list and
return, so announcing them would be a spinner that appears and vanishes within a
frame; a summary is a whole model request, and until this existed the chat simply
stopped for the length of it with nothing said. A run whose surface cannot show
anything leaves it `None` and the summary is silent, the way a delegation is
silent on a surface with no `subagent_events`.
"""


@dataclass
class AgentDeps:
    """Everything a tool may need that the model must not control."""

    organization_id: UUID | None = None
    user_id: str | None = None
    user_name: str | None = None
    agent_id: UUID | None = None
    run_id: UUID | None = None

    # The person's memory partition, derived server-side when memory is bound. `None`
    # means no per-person signal: reads fall back to shared, personal writes are refused.
    end_user_scope_key: str | None = None

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

    # Set when the surface can say "still working" while the history is being
    # summarised. None elsewhere, and the summary is then silent rather than
    # refused - it is a progress report, not a permission.
    on_compaction: CompactionSink | None = None

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
        delegate's own spec, and inheriting the parent's would hand a specialist a
        collection nobody granted it. The delegate's own are put back by the
        delegation capability, from `ResolvedSubagent.collection_names` - because
        the deps our factory built for the child are *this* object's replacement,
        so the collections resolved for it would otherwise be resolved and never
        read.

        Args:
            max_depth: How much further the library will let this delegate
                delegate, one less than the parent's `max_nesting_depth`.
                Deliberately not stored, and this is worth saying because storing
                it looks obviously right. Enforcement is not ours to do here: a
                delegate's own delegates have to be resolved from the database -
                their pinned versions, their collections, their secrets, each
                behind `resolve_access` - and this method runs mid-run on a
                session shared with the rest of the request, which is not
                concurrency-safe. So the bound is applied where the resolution
                happens, by walking the tree once before the run starts, and at
                the bound the child is simply built without the delegation
                capability. A copy of the number here would be a second answer
                that nothing consults.
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
            metadata=dict(self.metadata),
        )
