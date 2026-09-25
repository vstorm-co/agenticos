"""Schemas for groups - named sets of an organization's members."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.db.models.organization import MembershipSourceLiteral
from app.schemas.base import BaseSchema


class GroupCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)


class GroupUpdate(BaseSchema):
    """Rename a group or change its description; an omitted field is left as it is."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)


class GroupRead(BaseSchema):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None = None
    member_count: int = 0
    created_at: datetime


class GroupList(BaseSchema):
    items: list[GroupRead]
    total: int


class GroupMemberAdd(BaseSchema):
    user_id: UUID


class GroupMemberRead(BaseSchema):
    user_id: UUID
    email: str
    full_name: str | None = None
    source: MembershipSourceLiteral
    """`directory` when a directory group mapping put this person here; the next
    sign-in may take them out again. Adding them by hand makes it `manual`."""
    created_at: datetime


class GroupMemberList(BaseSchema):
    items: list[GroupMemberRead]
    total: int
