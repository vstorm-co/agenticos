"""Room roster and mention DTOs."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class RoomParticipantRef(BaseSchema):
    """A user or agent identity selected in a room."""

    kind: Literal["user", "agent"]
    id: UUID


class RoomMentionRead(RoomParticipantRef):
    """Canonical mention identity persisted on a room message."""

    name: str


class RoomParticipantRead(RoomMentionRead):
    """A roster entry or an eligible principal from the mention picker."""

    avatar_url: str | None = None
    is_member: bool = False
    can_add: bool = False
    can_mention: bool = False
    auto_reply: bool = False


class RoomParticipantsRead(BaseSchema):
    """The room roster and the current reader's write and management rights."""

    conversation_id: UUID
    visibility: Literal["private", "public"] | None
    can_post: bool = False
    can_manage: bool = False
    items: list[RoomParticipantRead] = Field(default_factory=list)


class RoomMentionableList(BaseSchema):
    """Current roster plus eligible organization people and agents."""

    items: list[RoomParticipantRead] = Field(default_factory=list)


class RoomParticipantAutoReplyUpdate(BaseSchema):
    """Change whether a room agent answers without an explicit mention."""

    auto_reply: bool


class RoomCreate(BaseSchema):
    """Create a room and optionally add its initial participants."""

    title: str = Field(min_length=1, max_length=255)
    visibility: Literal["private", "public"] = "private"
    participants: list[RoomParticipantRef] = Field(default_factory=list, max_length=100)
