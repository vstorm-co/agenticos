"""A saved browser sign-in, as its owner sees it (#2129).

Which site, and when - never what it holds. The cookies and storage are sealed in
the vault and no response carries them, which is what lets a person check what
they have kept without the list becoming a way to copy a session out.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema


class BrowserSignInRead(BaseSchema, TimestampSchema):
    """One saved sign-in: the site, when it was saved, when a browse last used it."""

    id: UUID
    site: str = Field(description="The host signed in to, without `www.`.")
    last_used_at: datetime | None = Field(
        default=None, description="When a browse last started signed in with it."
    )


class BrowserSignInList(BaseSchema):
    """The caller's saved sign-ins in this organization, by site."""

    items: list[BrowserSignInRead]
    total: int


class SignInBrowserRead(BaseSchema):
    """Whether this deployment can open a browser to sign in from Settings."""

    available: bool = Field(
        description="False when the deployment names no browser for it; the option is hidden."
    )


class SignInSessionCreate(BaseSchema):
    """The site to sign in to."""

    url: str = Field(
        min_length=1,
        max_length=2048,
        description="The page to open - usually the site's own sign-in page. Public http(s) only.",
    )


class SignInSessionRead(BaseSchema):
    """Where the opened browser is watched and driven: the live view of this run and call."""

    run_id: str
    call_id: str
