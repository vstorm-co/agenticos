"""Schemas for the app-admin announcement composer (#1598, Decision 5)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.core.permissions import OrgRoleName
from app.db.models.announcement import Announcement
from app.schemas.base import BaseSchema


class AnnouncementCreate(BaseSchema):
    """One send: a body, and an explicit audience.

    `organizations` is `"all"` or a non-empty list of organization ids -
    there is no default and no way to address zero organizations by
    omission, since the composer's whole point is an *explicit* audience.
    `role`, when given, narrows every selected organization (or the whole
    deployment, under `"all"`) to members holding that role - the same
    narrowing `security_event`'s `org_admins` audience already uses one
    layer down.
    """

    body: str = Field(min_length=1, max_length=4000)
    organizations: Literal["all"] | list[UUID] = Field(min_length=1)
    role: OrgRoleName | None = None

    @field_validator("organizations")
    @classmethod
    def _organizations_not_empty(
        cls, value: Literal["all"] | list[UUID]
    ) -> Literal["all"] | list[UUID]:
        # `Field(min_length=1)` only checks the list branch; `"all"` is a
        # string of length 3 and would pass the same constraint by accident,
        # so the empty-list case is guarded explicitly instead.
        if isinstance(value, list) and not value:
            raise ValueError('Select at least one organization, or "all"')
        return value


class AnnouncementRead(BaseSchema):
    id: UUID
    body: str
    audience_description: str
    recipient_count: int
    created_at: datetime

    @classmethod
    def from_row(cls, announcement: Announcement, *, recipient_count: int) -> AnnouncementRead:
        return cls(
            id=announcement.id,
            body=announcement.body,
            audience_description=announcement.audience_description,
            recipient_count=recipient_count,
            created_at=announcement.created_at,
        )
