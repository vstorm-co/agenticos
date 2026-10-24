"""The authoring assistant's proposed context file changes, as a reviewer reads them."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.resource_usage import AgentUsage, ReachedAgent


class ContextProposalRead(BaseSchema, TimestampSchema):
    """One proposed body for a context file, beside the file as it stands.

    Attributes:
        stale: Whether the file changed since the proposal was written; Apply
            refuses a stale proposal rather than throw that edit away.
        used_by: The agents whose draft binds the file, as far as the reader may
            see them - every one of them reads the new body once it is applied.
    """

    id: UUID
    context_id: UUID
    context_name: str
    description: str | None
    content: str
    current_description: str | None
    current_content: str
    status: str
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    stale: bool
    rationale: str = ""
    evidence: list[dict[str, str | None]] = Field(
        default_factory=list,
        description=(
            "Run ids and quotes, each checked against the run it names; the quote is "
            "null for a reader without runs:view"
        ),
    )
    evidence_dropped: int = 0
    expected_effect: str = ""
    authoring_request_id: UUID | None = None
    used_by: list[AgentUsage] = Field(default_factory=list)
    revision: int = Field(
        default=1, description="Raised each time a new run rewrites the pending proposal"
    )
    reaches: list[ReachedAgent] = Field(
        default_factory=list,
        description=(
            "The agents whose served version reads it - where applying it goes live at "
            "once - as far as the reader may see them"
        ),
    )
    reaches_hidden: int = Field(
        default=0, description="Agents it also reaches that the reader may not see"
    )


class ContextProposalList(BaseSchema):
    items: list[ContextProposalRead]
    total: int
