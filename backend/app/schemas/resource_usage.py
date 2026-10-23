"""Where a skill, a context file or a knowledge base is used (#2075)."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class AgentUsage(BaseSchema):
    """One agent whose draft binds the resource, named so a card can say which."""

    id: UUID
    name: str


class ReachedEnvironment(BaseSchema):
    """An environment of an agent whose served version reads the changed file or skill."""

    name: str
    guarded_by: list[str] = Field(
        default_factory=list,
        description=(
            "The eval suites that guard it, by name - empty for a reader without runs:view, "
            "for whom `guards` still counts them"
        ),
    )
    guards: int = Field(description="How many eval suites guard it")


class ReachedAgent(BaseSchema):
    """An agent a change reaches the moment it is applied, and where it goes live."""

    id: UUID
    name: str
    environments: list[ReachedEnvironment]


class ProposalDecision(BaseSchema):
    """Applying or discarding a proposed change: the revision the reviewer saw."""

    revision: int = Field(
        ge=1,
        description=(
            "The proposal's revision as the reviewer read it. A newer run rewrites a "
            "pending proposal and raises it, and the decision is then refused"
        ),
    )
