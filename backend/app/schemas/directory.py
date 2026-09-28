"""Schemas for directory group mappings and signing in with a directory account."""

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import BaseSchema
from app.schemas.organization import InvitableRole


class DirectoryMappingCreate(BaseSchema):
    """Map a directory group to a role, and optionally a group, in this organization."""

    external_group: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "The group exactly as the identity provider reports it: an LDAP group DN, "
            "or a value of the OIDC groups claim. Compared case-insensitively."
        ),
    )
    role: InvitableRole = Field(
        description="The role a member of the directory group holds here. Never owner."
    )
    group_id: UUID | None = Field(
        default=None, description="A group of this organization the member is also placed in."
    )

    @field_validator("external_group")
    @classmethod
    def case_folded(cls, value: str) -> str:
        """Stored the way it is matched, so the unique constraint means what the match does."""
        return value.casefold()


class DirectoryMappingRead(BaseSchema):
    id: UUID
    organization_id: UUID
    external_group: str
    role: str
    group_id: UUID | None = None
    group_name: str | None = None
    created_at: datetime


class DirectoryMappingList(BaseSchema):
    items: list[DirectoryMappingRead]
    total: int


class DirectoryLogin(BaseSchema):
    """A directory account's own credentials, checked by binding as it.

    Whitespace stripping is switched off for this model: the directory compares a
    password verbatim, so trimming one that ends in a space would refuse its owner
    with the right password - and an account whose password *is* spaces could not
    sign in at all. The username is stripped by its own validator instead.
    """

    model_config = ConfigDict(str_strip_whitespace=False)

    username: str = Field(min_length=1, max_length=256)
    # `min_length=1` refuses the empty password here as well as in the adapter,
    # because an LDAP simple bind with an empty password is an *unauthenticated*
    # bind that most servers answer with success (RFC 4513 s.5.1.2).
    password: str = Field(min_length=1, max_length=1024)
    invitation_handle: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "The handle of an invitation staged before signing in, so a first "
            "directory sign-in on an invite-only deployment is admitted by it"
        ),
    )

    @field_validator("username")
    @classmethod
    def trimmed(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("A username is required")
        return stripped
