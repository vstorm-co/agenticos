"""User schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.schemas.base import BaseSchema, TimestampSchema


class UserBase(BaseSchema):
    """Base user schema."""

    email: EmailStr = Field(max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.lower()


class UserCreate(UserBase):
    """Schema for creating a user."""

    password: str = Field(min_length=8, max_length=128)

    invitation_token: str | None = Field(default=None, max_length=64)
    """The invitation this registration is arriving through, when there is one.

    Only ever consulted by the sign-up policy, and only on a deployment that has
    narrowed who may register: holding a live invitation is what admits an address
    an `invite_only` deployment would otherwise refuse, and what overrides the
    domain allow-list. It grants nothing else - joining the organization is still
    `InvitationService.accept`, which the client calls once it has a session.

    It exists because the token is the *only* proof available for a shareable link
    with no address and no domain on it. Matching an invitation against the
    submitted address cannot see one of those, so before this an operator who
    closed sign-up had silently un-invited everybody holding one (#916).
    """


class UserUpdate(BaseSchema):
    """Schema for updating a user."""

    email: EmailStr | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    avatar_color: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Default-avatar colour, slot 1-10; send null to reset to auto.",
    )
    onboarding_completed_at: datetime | None = Field(
        default=None,
        description="Set to a timestamp to mark onboarding complete; null to reset.",
    )
    notify_budget_alerts: bool | None = Field(
        default=None,
        description="Email me when one of my agents stops on a spending limit.",
    )
    notify_approval_requests: bool | None = Field(
        default=None,
        description="Email me when a run parks waiting for a tool-call approval.",
    )
    notify_usage_reports: bool | None = Field(
        default=None,
        description="Email me the weekly and monthly usage reports.",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str | None) -> str | None:
        return v.lower() if v is not None else None


class UserRead(UserBase, TimestampSchema):
    """Schema for reading a user."""

    id: UUID
    # The platform-superadmin flag. Exposed so the frontend can decide whether
    # to show the /admin surface at all - the server re-checks it on every
    # admin endpoint, so a client that lies to itself gains nothing.
    is_app_admin: bool = False
    avatar_url: str | None = None
    avatar_color: int | None = None
    onboarding_completed_at: datetime | None = None
    notify_budget_alerts: bool = True
    notify_approval_requests: bool = True
    notify_usage_reports: bool = True


class UserInDB(UserRead):
    """User schema with hashed password (internal use)."""

    hashed_password: str


class AdminUserRead(BaseSchema):
    """Minimal user info for admin endpoints."""

    id: UUID
    email: str
    full_name: str | None = None
    is_active: bool = True
    is_app_admin: bool = False
    conversation_count: int = 0
    created_at: datetime


class AdminUserList(BaseSchema):
    """Paginated list of users for admin."""

    items: list[AdminUserRead]
    total: int


class ImpersonateResponse(BaseSchema):
    """An impersonation just opened: the token that is it, and the row it names.

    The token reaches the console's BFF, which puts it in the same HttpOnly cookie
    every other access token lives in - never into something a page could copy to
    a clipboard (#1044). `session_id` is the row the token names in its `sid`
    claim and the one ending it closes; `expires_at` is when it closes on its own.
    `impersonated_by` is who the row and the `act` claim name: in a nested chain,
    the human who started it rather than the account one hop up.
    """

    access_token: str
    token_type: str
    impersonated_user_id: str
    impersonated_by: str
    expires_in: int
    expires_at: datetime
    session_id: UUID


class ImpersonatorRead(BaseSchema):
    """The administrator behind an impersonated session, as the banner names them."""

    id: UUID
    email: str
    full_name: str | None = None


class ImpersonationRead(BaseSchema):
    """The impersonation a request runs under: who is acting, and until when."""

    session_id: UUID
    impersonator: ImpersonatorRead
    expires_at: datetime


class MeRead(UserRead):
    """`GET /auth/me`: the account this request acts as, and whether somebody else is.

    `impersonation` is set only while an administrator is acting as this account,
    and it is what the console draws its persistent banner from - the account's
    own fields say nothing about it, because they *are* the account (#1044).
    """

    impersonation: ImpersonationRead | None = None


class AdminUserMembership(BaseSchema):
    """One organization this person belongs to, and what they are in it."""

    organization_id: UUID
    name: str
    slug: str
    is_personal: bool
    role: str


class AdminUserDetail(BaseSchema):
    """What a deployment admin needs before deciding something about a person.

    The questions the user drawer exists to answer and could not: where does
    this person have access and with what authority, when were they last here,
    and is anything of theirs still signed in (#942). Separate from
    :class:`UserRead` because it is a *view*, assembled from three tables, and
    folding it into the row every other reader gets would make three queries the
    price of reading a user anywhere.
    """

    memberships: list[AdminUserMembership]
    last_seen_at: datetime | None = Field(
        default=None,
        description=(
            "The most recent activity on any of their sessions, or null for an account "
            "that has never signed in - which is not the same as a dormant one, and the "
            "drawer says so."
        ),
    )
    active_sessions: int = Field(
        default=0, description="How many sessions are still open, not how many ever were."
    )
    newest_session_at: datetime | None = None
