"""Remote A2A agents registered to delegate to (#2092)."""

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema


class ExternalAgentCreate(BaseSchema):
    """Register a remote agent by the address of its A2A agent card."""

    card_url: str = Field(
        min_length=8,
        max_length=1000,
        description=(
            "The agent card's URL, or the agent's base address - "
            "`/.well-known/agent-card.json` is appended to one that is not a JSON file."
        ),
    )
    slug: str | None = Field(
        default=None,
        max_length=64,
        description="The handle a delegating agent calls it by. Derived from its name if unset.",
    )
    secret_id: UUID | None = Field(
        default=None,
        description="An API key secret sent as its bearer token, when it asks for one.",
    )

    @field_validator("card_url")
    @classmethod
    def _no_credential_in_the_address(cls, card_url: str) -> str:
        """The address is stored as configuration; a key belongs in the vault."""
        parsed = urlsplit(card_url.strip())
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(
                "The card's address must not carry a user name or password - "
                "store the key in the vault and pick it here"
            )
        return card_url


class ExternalAgentSkill(BaseSchema):
    id: str
    name: str
    description: str


class ExternalAgentRead(BaseSchema):
    """A registered remote agent, as its card described it."""

    id: UUID
    slug: str
    name: str
    description: str
    card_url: str
    endpoint_url: str
    secret_id: UUID | None = None
    skills: list[ExternalAgentSkill] = Field(default_factory=list)
    can_manage: bool = Field(
        default=False,
        description="Whether the caller may refresh or remove it: whoever registered it, "
        "or somebody who edits every agent.",
    )
    created_at: datetime
    updated_at: datetime | None = None


class ExternalAgentList(BaseSchema):
    items: list[ExternalAgentRead]
