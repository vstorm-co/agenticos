"""Schemas for requests to share a page, or to confirm one of its versions (#1974)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.db.models.artifact_share_request import (
    MAX_NOTE_LENGTH,
    ShareRequestKind,
    ShareRequestStatus,
    VoidReason,
)
from app.db.models.resource_grant import GrantLevelLiteral
from app.schemas.artifact import (
    ArtifactVersionRead,
    BindingParts,
    DisclosedField,
    DisclosedFilter,
    DisclosedSort,
    WorkflowLogParts,
)
from app.schemas.base import BaseSchema
from app.schemas.resource_grant import VisibilityLiteral

Effect = Literal["widens", "narrows", "neutral"]


class ArtifactAccessRequestCreate(BaseSchema):
    """Ask for access to a page the caller cannot open."""

    note: str | None = Field(
        default=None, max_length=MAX_NOTE_LENGTH, description="Why, in a few words"
    )


class ShareRequestSubject(BaseSchema):
    """One person or group an `audience` request asks to share the page with."""

    level: GrantLevelLiteral
    user_id: UUID | None = None
    email: str | None = None
    group_id: UUID | None = None
    group_name: str | None = None


class ArtifactShareRequestRead(BaseSchema):
    """One request, with the names to show it by. Never what the page's data holds."""

    id: UUID
    artifact_id: UUID
    kind: ShareRequestKind = Field(
        description=(
            "`audience`: an editor asks to widen who opens a page that reads data; `access`: "
            "a member asks to open it; `version`: a republish changed what it reads"
        )
    )
    status: ShareRequestStatus
    requester_user_id: UUID
    requester_name: str | None = None
    version_id: UUID | None = Field(
        default=None, description="The version it was made against, or is about"
    )
    version_number: int | None = None
    query_fingerprint: str | None = Field(
        default=None, description="The page queries it was made against; what an approval confirms"
    )
    requested_visibility: VisibilityLiteral | None = None
    requested_subjects: list[ShareRequestSubject] = Field(default_factory=list)
    note: str | None = None
    void_reason: VoidReason | None = None
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime
    can_decide: bool = Field(
        description="Whether the caller may approve or decline it - always false once decided"
    )


class ArtifactShareRequestList(BaseSchema):
    items: list[ArtifactShareRequestRead]
    total: int


class ArtifactAccessRequested(BaseSchema):
    """What someone who cannot open a page is told of the request they filed for it:
    nothing about the page."""

    id: UUID
    kind: ShareRequestKind
    status: ShareRequestStatus
    created_at: datetime
    note: str | None = None


ChangeValue = DisclosedField | DisclosedFilter | DisclosedSort | WorkflowLogParts | str | int


class BindingChange(BaseSchema):
    """One difference between a binding's page query in two versions."""

    aspect: Literal["table", "field", "filter", "sort", "limit", "linked", "reach", "log", "kind"]
    change: Literal["added", "removed", "changed"]
    effect: Effect = Field(
        description=(
            "`widens`: more is read than before - a column, a linked table, a larger limit, "
            "a condition dropped or loosened, another order, a column read only by a condition "
            "or the order; `narrows`: less; `neutral`: nothing the audience reads"
        )
    )
    before: ChangeValue | None = None
    after: ChangeValue | None = None


class BindingReview(BaseSchema):
    """One binding that differs between the two versions."""

    name: str
    change: Literal["added", "removed", "changed"]
    effect: Effect
    parts: BindingParts | WorkflowLogParts | None = Field(
        default=None,
        description="An added binding's whole page query, or a removed one's last",
    )
    changes: list[BindingChange] = Field(
        default_factory=list, description="What differs, for a binding in both versions"
    )


class ArtifactVersionReview(BaseSchema):
    """A version's page queries against the version the page's audience is served."""

    version: ArtifactVersionRead
    compared_to: int | None = Field(
        default=None,
        description="The number of the audience's version; null when it is served none yet",
    )
    publisher_name: str | None = None
    bindings: list[BindingReview]
    unchanged: list[str] = Field(description="The bindings that read the same in both")
    widens: bool = Field(description="Whether anything in it reads more than the audience's")
    problem: str | None = Field(
        default=None, description="Why the words are incomplete: a table nobody can read"
    )
