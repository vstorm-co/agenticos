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
    """Response schema for admin user impersonation."""

    access_token: str
    token_type: str
    impersonated_user_id: str
    impersonated_by: str
    expires_in: int
