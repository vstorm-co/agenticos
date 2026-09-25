"""Schemas for per-resource sharing."""

from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.db.models.resource_grant import GrantLevelLiteral
from app.schemas.base import BaseSchema

VisibilityLiteral = Literal["private", "team", "org"]


def as_visibility(value: str) -> VisibilityLiteral:
    """One column's string as the vocabulary the API publishes.

    A visibility is a `String` column under a check constraint, so what comes
    back from the database is `str` as far as anything reading it can tell. This
    is where that becomes the three values the schema promises - and where a row
    holding anything else fails loudly, rather than being serialized into a
    response whose own OpenAPI schema forbids it.
    """
    match value:
        case "private" | "team" | "org":
            return value
        case _:
            raise ValueError(f"Not a visibility: {value!r}")


class ResourceGrantRead(BaseSchema):
    """One member's or one group's access to one resource.

    Exactly one of `subject_user_id` and `subject_group_id` is set - the
    database's `ck_resource_grant_one_subject` holds it, so a client can branch
    on which is present.
    """

    id: UUID
    subject_user_id: UUID | None = None
    subject_email: str | None = None
    subject_group_id: UUID | None = None
    subject_group_name: str | None = None
    resource_type: str
    resource_id: UUID
    level: GrantLevelLiteral

    @classmethod
    def of(
        cls,
        grant: Any,
        *,
        emails: Mapping[UUID, str | None],
        group_names: Mapping[UUID, str],
    ) -> "ResourceGrantRead":
        """One grant row as the API shows it, with its subject's name resolved."""
        user_id: UUID | None = grant.subject_user_id
        group_id: UUID | None = grant.subject_group_id
        return cls(
            id=grant.id,
            subject_user_id=user_id,
            subject_email=emails.get(user_id) if user_id is not None else None,
            subject_group_id=group_id,
            subject_group_name=group_names.get(group_id) if group_id is not None else None,
            resource_type=grant.resource_type,
            resource_id=grant.resource_id,
            level=grant.level,
        )


class ResourceGrantUpsert(BaseSchema):
    """Share a resource with a member or a group, or change the level of an existing share."""

    subject_user_id: UUID | None = None
    subject_group_id: UUID | None = None
    level: GrantLevelLiteral = Field(
        default="read",
        description="read sees the configuration, use also runs it, edit also changes it",
    )

    @model_validator(mode="after")
    def one_subject(self) -> "ResourceGrantUpsert":
        """A share has one subject: a person or a group, named by exactly one field."""
        if (self.subject_user_id is None) == (self.subject_group_id is None):
            raise ValueError("Name exactly one of subject_user_id and subject_group_id")
        return self


class ResourceSharing(BaseSchema):
    """The whole sharing state of one resource: who owns it, how visible it is, who it is shared with."""

    resource_type: str
    resource_id: UUID
    owner_user_id: UUID | None
    visibility: VisibilityLiteral
    grants: list[ResourceGrantRead]

    @classmethod
    def of(
        cls,
        resource: Any,
        *,
        resource_type: str,
        grants: Sequence[Any],
        emails: Mapping[UUID, str | None],
        group_names: Mapping[UUID, str],
    ) -> "ResourceSharing":
        """Assemble the response from a row, its grants and the looked-up names.

        On the schema rather than in the route module: turning rows into the
        response shape is what a schema is for, and the route that had it was
        the only thing standing between three resource types and a fourth
        copying it.

        `emails` and `group_names` are separate lookups because a grant stores
        an id and the UI shows a name; a grant for somebody no longer in the
        organization resolves to `None` rather than dropping the row, so an
        admin can still see - and revoke - access nobody can explain.
        """
        return cls(
            resource_type=resource_type,
            resource_id=resource.id,
            owner_user_id=resource.owner_user_id,
            visibility=resource.visibility,
            grants=[
                ResourceGrantRead.of(grant, emails=emails, group_names=group_names)
                for grant in grants
            ],
        )


class VisibilityUpdate(BaseSchema):
    """Change how widely a resource is exposed within its organization."""

    visibility: VisibilityLiteral
