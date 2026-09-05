"""Schemas for the deployment's identity, access policy and notices.

Three shapes, and what separates them is **who is allowed to read what**:

- :class:`BrandingRead` is answered to **anybody**, signed in or not. It has to
  be: the favicon is served above every tenant and the sign-in page is rendered
  before a session exists, so a page that could not read this could not render
  its own name. Everything in it is therefore something a stranger loading the
  login screen may know anyway - what the installation is called, what it looks
  like, whose terms it links to, whether they may register, and whether it is
  open at all.
- :class:`NoticeRead` is the banner, and it is answered to a **signed-in user
  only**. An announcement is written for the people using the deployment - "the
  Postgres upgrade starts at 22:00, ping ops" - and there is no reason for a
  stranger to read an operator's plans.
- :class:`DeploymentSettingsRead` is the administrator's own view: the public
  shape plus the notice fields, so one request fills one form.

**Null means "the built-in", everywhere.** The API answers what was *overridden*,
not what is effective, and each renderer resolves a null against its own default -
the frontend against `APP_NAME` and `SITE` in `frontend/src/lib/`, the backend
against `settings.PROJECT_NAME` for the text it sends itself.
`tests/test_deployment_branding.py` pins those two built-ins equal, which is the
only thing keeping a rename in one from disagreeing with the other.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema

SignupMode = Literal["open", "invite_only", "closed"]
"""Who may create an account. `app/services/signup_policy.py` is where it is applied."""

NoticeLevel = Literal["info", "warning", "critical"]

_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
"""A hostname with at least one dot. Deliberately not an email regex: the column
holds `acme.com`, and `@acme.com` or `me@acme.com` are both operator slips worth a
422 rather than a rule that silently matches nothing."""

MAX_ALLOWED_DOMAINS = 32
"""Enough for a group of companies, small enough that the list stays readable and
the `endswith` sweep in the signup policy stays a constant-time detail."""


def _http_url(value: str | None, field: str) -> str | None:
    """A caller-supplied link, or a 422 naming the field that is wrong.

    Scheme and host are both required: `www.acme.com/terms` parses cleanly, has no
    scheme, and renders as a relative link back into this app - a "terms" link that
    404s on our own domain rather than reaching theirs.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute http(s) URL")
    return trimmed


class BrandingRead(BaseSchema):
    """What this deployment calls itself - readable without a session."""

    app_name: str | None = None
    tagline: str | None = None
    description: str | None = None

    logo_version: int | None = None
    """When the stored wordmark was last written, or null when there is none.

    A version rather than a URL, and neither is the storage key - which is an
    implementation detail of whichever backend is configured, and would let a caller
    address the store directly. The address itself is `GET /branding/logo` beside
    this, so what a client actually needs from the row is *whether* there is an image
    and *when it changed*: the address is constant, the bytes are served `immutable`
    for a year, and without a token that moves, a browser holding the previous logo
    has no reason to ask again.

    It is also the honest half to publish. A browser cannot use this API's own
    address in any deployment where the API is not on the same origin as the pages,
    so a URL here would be one every client had to rewrite.
    """

    favicon_version: int | None = None

    footer_text: str | None = None
    terms_url: str | None = None
    privacy_url: str | None = None

    signup_mode: SignupMode = "open"
    allowed_email_domains: list[str] = Field(default_factory=list)
    """Published on purpose. A sign-up form that refuses an address *after* it is
    typed, without ever saying which addresses it wants, is a form that lies; the
    domains are also not a secret, since the deployment is on the company's own
    host."""

    maintenance_mode: bool = False
    maintenance_message: str | None = None


class NoticeRead(BaseSchema):
    """What a signed-in surface has to keep asking about.

    Two things, because a page already open has to learn both of them without
    being reloaded: the administrator's announcement, and whether the deployment
    has since been closed for maintenance. The maintenance verdict is in
    `BrandingRead` as well, but that one is resolved once by the server layout and
    then never changes for the life of the page - so a window opened afterwards
    left every open tab on a dashboard whose requests had started answering 503,
    and closing one left a tab stuck on the maintenance screen. This is the
    polled answer.
    """

    message: str | None = None
    level: NoticeLevel = "info"
    maintenance_mode: bool = False
    maintenance_message: str | None = None


class DeploymentLimits(BaseSchema):
    """What one account and one organization may hold, or nothing for no ceiling.

    Deliberately absent from `BrandingRead`, which is served without a session: a
    ceiling is operational, and a stranger on the sign-in page has no part in it.
    """

    organizations_per_user: int | None = None
    agents_per_organization: int | None = None


class DeploymentSettingsRead(BrandingRead):
    """The administrator's view: everything, in one request."""

    announcement: str | None = None
    announcement_level: NoticeLevel = "info"
    max_organizations_per_user: int | None = None
    max_agents_per_organization: int | None = None
    notify_impersonated_users: bool = False
    """Whether somebody is emailed when an administrator acts as them.

    Here and not in `BrandingRead`: what the deployment tells its own users about
    administrator access is the administrator's business, not a stranger's on the
    sign-in page.
    """
    updated_at: datetime | None = None


class DeploymentSettingsUpdate(BaseSchema):
    """A partial write. Every field is optional; `null` clears an override.

    "Clears" rather than "blanks": a nullable column keeps the explicit `null` and
    the renderer falls back to its built-in, while a `null` for a `NOT NULL` column -
    `signup_mode`, `maintenance_mode` - is dropped by `app/db/updates.writable`
    rather than reaching the row as a 500. The image columns are not here at all:
    a path is written only by the upload route, which puts the bytes there itself.
    """

    app_name: str | None = Field(default=None, max_length=64)
    tagline: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=320)

    footer_text: str | None = Field(default=None, max_length=280)
    terms_url: str | None = Field(default=None, max_length=512)
    privacy_url: str | None = Field(default=None, max_length=512)

    signup_mode: SignupMode | None = None
    allowed_email_domains: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_DOMAINS)

    announcement: str | None = Field(default=None, max_length=500)
    announcement_level: NoticeLevel | None = None

    maintenance_mode: bool | None = None
    maintenance_message: str | None = Field(default=None, max_length=500)

    # Null clears the ceiling, which is the same as never having set one. `ge=1`
    # because zero is not a limit anybody means: it would leave an account that
    # cannot own the personal organization sign-up creates for it.
    max_organizations_per_user: int | None = Field(default=None, ge=1, le=10_000)
    max_agents_per_organization: int | None = Field(default=None, ge=1, le=10_000)

    notify_impersonated_users: bool | None = None

    @field_validator("app_name", "tagline", "description", "footer_text", mode="after")
    @classmethod
    def _blank_is_cleared(cls, value: str | None) -> str | None:
        """An emptied input means "give me the built-in back".

        `str_strip_whitespace` has already trimmed it, so what arrives here is
        `""` - and storing that would render a sign-in page with no name on it,
        which is not what clearing a field asks for.
        """
        return value or None

    @field_validator("terms_url", "privacy_url", mode="after")
    @classmethod
    def _absolute_link(cls, value: str | None, info: object) -> str | None:
        field = getattr(info, "field_name", "url")
        return _http_url(value, field)

    @field_validator("allowed_email_domains", mode="after")
    @classmethod
    def _domains(cls, value: list[str] | None) -> list[str] | None:
        """Lower-cased, de-duplicated, order kept, and each one a real hostname.

        Normalised here rather than at the point of comparison: the signup policy
        matches a candidate address against this list on every registration, and a
        list holding `Acme.COM` would refuse `me@acme.com` for a rule the operator
        believes they wrote.
        """
        if value is None:
            return None
        seen: dict[str, None] = {}
        for raw in value:
            domain = raw.strip().lower().removeprefix("@")
            if not domain:
                continue
            if not _DOMAIN.match(domain):
                raise ValueError(f"'{raw}' is not a domain name")
            seen[domain] = None
        return list(seen)
