"""Where a skill, a context file or a knowledge base is used (#2075)."""

from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class AgentUsage(BaseSchema):
    """One agent whose draft binds the resource, named so a card can say which."""

    id: UUID
    name: str


class ReachedAgent(BaseSchema):
    """An agent a change reaches the moment it is applied, and what checks it.

    Suites are named for a reader of runs - eval suites are read under
    `runs:view` - and counted for anybody else.
    """

    id: UUID
    name: str
    environments: list[str] = Field(description="Where the change goes live for it, by name")
    runs_now: list[str] = Field(
        default_factory=list,
        description="The eval suites applying it queues - those run when a dependency changes",
    )
    runs_now_count: int = 0
    at_promotion: list[str] = Field(
        default_factory=list,
        description=(
            "The suites guarding those environments that do not run on the change: they "
            "check the agent at its next promotion"
        ),
    )
    at_promotion_count: int = 0


class ProposalDecision(BaseSchema):
    """Applying or discarding a proposed change: the revision the reviewer saw."""

    revision: int = Field(
        ge=1,
        description=(
            "The proposal's revision as the reviewer read it. A newer run rewrites a "
            "pending proposal and raises it, and the decision is then refused"
        ),
    )
