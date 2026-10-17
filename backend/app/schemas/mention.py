"""What a person can point an agent at with `@` in the chat composer (#2189)."""

from typing import Literal

from pydantic import Field

from app.schemas.base import BaseSchema

MentionKind = Literal["mcp", "agent", "collection", "skill", "context"]


class MentionRef(BaseSchema):
    """One mention as a chat frame carries it: what kind of thing, and which."""

    kind: MentionKind
    id: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "The thing's id: a connection or agent id, a collection, skill or context "
            "file id, a catalog key for a person's own MCP account, or `platform`"
        ),
    )


class Mentionable(MentionRef):
    """Something the person may point the agent at, as the composer lists it."""

    name: str
    detail: str | None = Field(
        default=None,
        description="A short line under the name: the MCP tools' prefix, or what an agent does",
    )
    icon: str | None = Field(default=None, description="The catalog's mark, for an MCP server")
    slug: str | None = Field(default=None, description="An agent's handle, for its face")
    has_avatar: bool = False
    avatar_color: int | None = None
    delegate: bool = Field(
        default=False,
        description=(
            "For an agent: whether the chat's agent hands work to it as a delegate. "
            "Otherwise mentioning it runs the turn on it."
        ),
    )


class MentionableList(BaseSchema):
    items: list[Mentionable]
    total: int
