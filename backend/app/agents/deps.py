"""Dependencies handed to every tool call.

``AgentDeps`` is the only channel through which a tool learns anything the model
did not tell it: which collections the agent may search, what the tool was
configured with, who is asking. That separation is the security boundary — a
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

    metadata: dict[str, Any] = field(default_factory=dict)
