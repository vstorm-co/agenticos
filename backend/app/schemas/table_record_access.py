"""Read and Write grants on individual table records."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, model_validator

from app.schemas.base import BaseSchema

RecordAccessLevel = Literal["read", "write"]


class RecordGrantUpdate(BaseSchema):
    """Give one organization member or group Read or Write access to one row.

    Write includes Read and changes to ordinary cells. It does not grant table
    administration, deletion, access management or access to linked records.
    Group grants default to 90 days; member grants may be permanent.
    """

    model_config = ConfigDict(extra="forbid")

    subject_user_id: UUID | None = None
    subject_group_id: UUID | None = None
    level: RecordAccessLevel
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def one_subject(self) -> Self:
        if (self.subject_user_id is None) == (self.subject_group_id is None):
            raise ValueError("Name exactly one of subject_user_id and subject_group_id")
        return self


class RecordGrantRead(BaseSchema):
    """One explicit row grant, including expired grants available for renewal."""

    id: UUID
    subject_user_id: UUID | None = None
    subject_email: str | None = None
    subject_group_id: UUID | None = None
    subject_group_name: str | None = None
    level: RecordAccessLevel
    expires_at: datetime | None = None


class RecordAccessRead(BaseSchema):
    """The explicit grants managed on a row; table and policy rules still apply."""

    table_id: UUID
    record_id: UUID
    grants: list[RecordGrantRead]
