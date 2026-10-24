"""What an agent proposed changing about a skill, as a reviewer sees it.

The full body is in the read model on purpose. A reviewer deciding whether an
agent's rewrite of a policy should become the policy has to read it, and a
listing that showed only a name would make the decision a coin flip with an
audit trail.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.resource_usage import ReachedAgent


class SkillProposalRead(BaseSchema, TimestampSchema):
    id: UUID
    skill_id: UUID | None = Field(
        default=None, description="The skill this edits; null for one the agent wrote from nothing"
    )
    agent_id: UUID | None = None
    conversation_id: UUID | None = Field(
        default=None,
        description="Where it was written, so the exchange behind it can be read",
    )
    name: str
    description: str
    content: str
    resources: dict[str, str] = Field(
        default_factory=dict, description="The resource files, as name to content"
    )
    status: str
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    base_version: int | None = Field(
        default=None,
        description=(
            "The skill version the body was written against; Apply refuses once the "
            "skill has moved past it. Null for a change an agent's workspace wrote"
        ),
    )
    rationale: str = ""
    evidence: list[dict[str, str | None]] = Field(
        default_factory=list,
        description=(
            "Run ids and quotes, each checked against the run it names; the quote is "
            "null for a reader without runs:view"
        ),
    )
    evidence_dropped: int = Field(
        default=0, description="Evidence the assistant cited that could not be found"
    )
    expected_effect: str = ""
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


class SkillProposalList(BaseSchema):
    items: list[SkillProposalRead]
    total: int
