"""Schemas for organization secrets.

No schema here can carry a value outward. `SecretRead` exposes a name, a kind
and four characters, and there is deliberately no endpoint that returns a
plaintext - reading one is the runtime's privilege, not a client's.
"""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.secret_kinds import SecretKind, SecretKindInfo, StorableSecret
from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.resource_grant import VisibilityLiteral


class SecretCreate(BaseSchema):
    name: str = Field(
        min_length=1, max_length=128, description="How this secret is picked in the Builder"
    )
    description: str | None = Field(
        default=None, max_length=1000, description="What it is for, shown next to the picker"
    )
    value: StorableSecret = Field(
        description="The secret itself, discriminated by `kind`; sealed before storage"
    )
    purpose: str = Field(
        default="custom",
        max_length=32,
        description=(
            "What the key is for - see GET /secrets/purposes. This is what lets the "
            "model picker offer the providers you hold keys for, and a capability ask "
            "for the right key rather than for 'an API key'."
        ),
    )
    visibility: VisibilityLiteral = Field(
        default="org",
        description=(
            "private: yours alone; team: named members you share it with; "
            "org: everybody in this organization"
        ),
    )


class SecretUpdate(BaseSchema):
    """Rename, re-describe or rotate. Every field is optional; the kind is fixed."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    value: StorableSecret | None = Field(
        default=None, description="A replacement value of the same kind"
    )


class SecretPurposeRead(BaseSchema):
    """One thing a secret can be for, as the vault offers it."""

    id: str
    label: str
    category: Literal["model_provider", "search", "observability", "connector", "other"]
    kind: SecretKind
    help_url: str | None = None
    description: str = ""
    icon: str = Field(
        default="",
        description=(
            "The brand mark to draw, as the console's own glyph table names them. "
            "Empty falls back to a monogram - the honest floor for a service whose "
            "brand has no mark, and for a model provider, whose id already is one"
        ),
    )


class SecretPurposeList(BaseSchema):
    items: list[SecretPurposeRead]
    total: int


class SecretUsage(BaseSchema):
    """One place a stored key is bound. Named so the answer is readable."""

    kind: Literal["agent"]
    id: UUID
    name: str


class SecretRead(BaseSchema, TimestampSchema):
    id: UUID
    name: str
    description: str | None = None
    kind: SecretKind
    hint: str = Field(description="Four characters of the secret - never the secret itself")
    purpose: str = Field(
        default="custom",
        description="What the key is for - a provider id, a service id, or 'custom'",
    )
    visibility: VisibilityLiteral = Field(
        default="org",
        description="private: the owner's own; team: named members; org: everybody here",
    )
    owner_user_id: UUID | None = None
    owner_email: str | None = Field(
        default=None, description="Whose key it is, when it belongs to one person"
    )
    created_by_user_id: UUID | None = Field(
        default=None,
        description=(
            "Who stored it, by id - the stable seed the listing draws their fallback "
            "avatar from, so the same person wears one colour here and in member lists. "
            "Outlives the account: still set once they have left, when the email is null."
        ),
    )
    created_by_email: str | None = Field(
        default=None,
        description=(
            "Who stored it. Null when that account has since left the organization - "
            "the key outlives the person, which is itself worth seeing."
        ),
    )
    created_by_avatar_url: str | None = Field(
        default=None, description="The author's avatar, for a listing that shows a face"
    )
    shared_with: int = Field(
        default=0,
        description=(
            "How many people hold an explicit grant on this key. Meaningful next to "
            "visibility, not instead of it: an org-wide key reaches everyone regardless."
        ),
    )
    used_by: list[SecretUsage] = Field(
        default_factory=list,
        description=(
            "What breaks if this is deleted. An empty list is the useful case: a key "
            "nothing binds is one nobody can account for."
        ),
    )


class SecretList(BaseSchema):
    items: list[SecretRead]
    total: int


class SecretKindList(BaseSchema):
    """The kinds a secret can be, with the schema each form is generated from."""

    items: list[SecretKindInfo]
    total: int
