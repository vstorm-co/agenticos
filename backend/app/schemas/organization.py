"""Organization, OrganizationMember and Invitation schemas."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, EmailStr, Field, field_validator

from app.core.permissions import OrgRoleName
from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.user import UserRead

_ID = UUID

# The organization's monthly ceiling, as a client states it. Constrained inside
# the union rather than on the field so that `null` stays a legal value: it is
# how the cap is *removed*, and a `gt=0` applied to the whole field would
# reject the one request that lifts the limit.
MonthlyBudgetUsd = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=6)]


class OrganizationCreate(BaseSchema):
    name: str = Field(min_length=2, max_length=128)
    slug: str | None = Field(default=None, min_length=2, max_length=64)

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$", v):
            raise ValueError(
                "Slug must be lowercase alphanumeric with hyphens, no leading/trailing hyphens"
            )
        return v


class OrganizationUpdate(BaseSchema):
    """A partial update to an organization's settings.

    `monthly_budget_usd` and `avatar_color` are the fields where omitting them
    and sending `null` mean different things: absent leaves the setting as it
    stands, `null` clears it (removes the cap; resets the colour to auto).
    Renaming an organization must not uncap it or reset its colour, so the
    service keys on whether the client named the field rather than on its value.
    """

    name: str | None = Field(default=None, min_length=2, max_length=128)
    avatar_url: str | None = Field(default=None, max_length=500)
    avatar_color: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Default-avatar colour, slot 1-10; send null to reset to auto.",
    )
    monthly_budget_usd: MonthlyBudgetUsd | None = Field(
        default=None,
        description=(
            "Dollars this organization's agents may spend in a calendar month, "
            "or null for no limit. Omit to leave the current setting alone."
        ),
    )


class OrganizationRead(BaseSchema, TimestampSchema):
    id: _ID
    name: str
    slug: str
    is_personal: bool
    avatar_url: str | None = None
    avatar_color: int | None = None
    member_count: int = 0
    role: str  # current user's role in this org
    monthly_budget_usd: Decimal | None = None


class OrganizationList(BaseSchema):
    items: list[OrganizationRead]
    total: int


class OrganizationMemberRead(BaseSchema):
    id: _ID
    organization_id: _ID
    user_id: _ID
    role: str
    email: str
    full_name: str | None = None
    avatar_url: str | None = None
    avatar_color: int | None = None
    joined_at: datetime
    can_change_role: bool = False
    """Whether the caller listing may change this member's role - the server's
    own answer to `change_role`'s rule, so the client renders a selector only
    where a change would be accepted rather than one that 403s (#700)."""


class OrganizationMemberUpdate(BaseSchema):
    role: str = Field(description="New role for the member")

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        # A role change cannot make a second owner - ownership transfers
        # explicitly, and transfer-ownership demotes the outgoing owner (#672).
        allowed = {role.value for role in OrgRoleName} - {OrgRoleName.OWNER.value}
        if v not in allowed:
            raise ValueError(f"Role must be one of: {', '.join(sorted(allowed))}")
        return v


class OrganizationMemberList(BaseSchema):
    items: list[OrganizationMemberRead]
    total: int


def _invitable_role(v: str) -> str:
    allowed = {role.value for role in OrgRoleName} - {OrgRoleName.OWNER.value}
    if v not in allowed:
        raise ValueError(f"Role must be one of: {', '.join(sorted(allowed))}")
    return v


# An invitation cannot make someone an owner - ownership transfers explicitly.
# A link takes the same bound: it is built to be shared, so an unvalidated role
# on it was a mintable owner credential (#551).
InvitableRole = Annotated[str, AfterValidator(_invitable_role)]


class InvitationCreate(BaseSchema):
    email: EmailStr
    role: InvitableRole = "member"


class InviteLinkCreate(BaseSchema):
    """A shareable link, as an administrator asks for one."""

    role: InvitableRole = "member"
    max_uses: int | None = Field(
        default=None,
        ge=1,
        le=500,
        description="How many people it admits; null is unlimited",
    )
    email_domain: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Restrict to addresses at this domain. An unlimited link with no "
            "domain only holds while the URL itself is treated as a secret, "
            "which a link pasted into a channel is not."
        ),
    )


class InvitationRead(BaseSchema):
    """An invitation as anyone reading the organization's list sees it.

    Deliberately without the token. A token is a bearer credential - whoever
    holds one joins the organization as the role offered to somebody else's
    address - and this model is what `GET /orgs/{id}/invitations` returns, so
    carrying the token here handed out every pending credential on every call.
    Email, role, status and expiry are what an administrator decides on;
    revoking addresses the invitation by `id`.
    """

    id: _ID
    organization_id: _ID
    # Null makes this a link rather than an invitation to one address.
    email: str | None = None
    role: str
    status: str
    max_uses: int | None = None
    used_count: int = 0
    #: How many people registered through this link and have not joined yet.
    #:
    #: Beside `used_count` rather than folded into it, because they are different
    #: facts about the same ceiling: one is who is in, the other is who spent a use
    #: getting an account. `max_uses` is compared against their sum, so a console
    #: showing only the acceptances would say a spent link had a place left. The
    #: count, never the addresses - who registered under a link is not something a
    #: list of invitations publishes.
    reserved_count: int = 0
    email_domain: str | None = None
    expires_at: datetime
    created_at: datetime
    invited_by: UserRead | None = None


class InvitationCreated(InvitationRead):
    """The one response that carries the token, returned to the inviter once.

    The invitation is delivered by email; this is the copy of the link for the
    person who just sent it, for when the mail does not arrive. Nothing reads it
    back afterwards - there is no endpoint that returns a stored token.
    """

    invitation_token: str


class InvitationList(BaseSchema):
    items: list[InvitationRead]
    total: int


class InvitationAccept(BaseSchema):
    token: str


class TransferOwnershipRequest(BaseSchema):
    new_owner_user_id: _ID
