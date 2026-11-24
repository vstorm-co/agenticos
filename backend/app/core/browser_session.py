"""Sealed provenance and bounded cookie state for permanently protected continuations.

Cookies are not evidence of successful authentication or of safe page output.
Neither this state nor its descendants may enter the legacy ordinary-output loader.
"""

import json
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationRefused
from app.core.browser_origins import browser_origin

MAX_SESSION_COOKIES = 100
MAX_SESSION_BYTES = 65_536
MAX_SESSION_AGE_SECONDS = 7 * 24 * 60 * 60


def request_at_origin(url: str, origin: str) -> bool:
    """Exact HTTPS scheme/host/port, including redirects and subresource requests."""
    try:
        request, target = urlsplit(url), urlsplit(origin)
        allowed = (
            request.scheme == "https"
            and request.hostname == target.hostname
            and (request.port or 443) == (target.port or 443)
            and request.username is None
            and request.password is None
        )
    except ValueError:
        return False
    return allowed


class ProtectedCookie(BaseModel):
    """Host-only HTTPS cookie attributes; all page-chosen strings are repr-masked."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, revalidate_instances="always"
    )

    name: SecretStr = Field(min_length=1, max_length=256)
    value: SecretStr = Field(max_length=4096)
    path: SecretStr = Field(min_length=1, max_length=1024)
    http_only: bool
    same_site: Literal["Strict", "Lax", "None"] | None
    expires: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @field_validator("name", "value", "path")
    @classmethod
    def _no_controls(cls, value: SecretStr) -> SecretStr:
        if any(ord(char) < 32 or ord(char) == 127 for char in value.get_secret_value()):
            raise ValueError("Unsupported cookie state")
        return value

    @field_validator("path")
    @classmethod
    def _path(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("/"):
            raise ValueError("Unsupported cookie path")
        return value

    @field_serializer("name", "value", "path", when_used="json")
    def _seal_value(self, value: SecretStr) -> str:
        # Only the vault writer serializes this private model. It is never an API DTO.
        return value.get_secret_value()


class CredentialGeneration(BaseModel):
    """A contributing source, including a claimed write whose outcome is unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    secret_id: UUID
    authorization_generation: UUID


def credential_generations(
    values: list[CredentialGeneration] | tuple[CredentialGeneration, ...],
) -> tuple[CredentialGeneration, ...]:
    unique = {value.secret_id: value for value in values}
    if not unique or len(unique) > 50 or any(unique[value.secret_id] != value for value in values):
        raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED)
    return tuple(unique[key] for key in sorted(unique))


class CredentialSessionProvenance(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, revalidate_instances="always"
    )

    kind: Literal["credential_session_v1"] = "credential_session_v1"
    organization_id: UUID
    user_id: UUID
    agent_id: UUID
    continuation_id: UUID
    source_submission_id: UUID
    source_fill_id: UUID
    secret_id: UUID
    authorization_generation: UUID
    credential_generations: tuple[CredentialGeneration, ...] = Field(min_length=1, max_length=50)
    origin: str
    created_at: datetime
    expires_at: datetime
    output_protected: Literal[True] = True

    _origin = field_validator("origin")(browser_origin)

    @model_validator(mode="after")
    def _bounded_lifetime(self) -> CredentialSessionProvenance:
        if (
            self.created_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or not 0
            < (self.expires_at - self.created_at).total_seconds()
            <= MAX_SESSION_AGE_SECONDS
        ):
            raise ValueError("Protected session lifetime is invalid")
        if (
            credential_generations(self.credential_generations) != self.credential_generations
            or CredentialGeneration(
                secret_id=self.secret_id, authorization_generation=self.authorization_generation
            )
            not in self.credential_generations
        ):
            raise ValueError("Protected session provenance is invalid")
        return self


class ProtectedSignIn(BaseModel):
    """The encrypted payload, never a field in API, model, event, trace or checkpoint output."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, revalidate_instances="always"
    )

    provenance: CredentialSessionProvenance
    cookies: tuple[ProtectedCookie, ...] = Field(
        min_length=1, max_length=MAX_SESSION_COOKIES, repr=False
    )


def bounded_cookies(origin: str, raw: object, *, now: float) -> tuple[ProtectedCookie, ...]:
    """Project exact host-only cookies from the owning context; never broaden domains.

    Storage.getCookies enumerates a context, not an origin. Domain cookies and
    partitioned cookies are excluded; those would carry a different audience.
    The fresh context admits only the exact HTTPS origin when restoring these.
    """
    host = urlsplit(browser_origin(origin)).hostname
    if not isinstance(raw, list) or len(raw) > 300:
        raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED)
    chosen: list[ProtectedCookie] = []
    total = 0
    for item in raw:
        if not isinstance(item, dict):
            raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED)
        if item.get("domain") != host:
            continue
        if (
            item.get("secure") is not True
            or item.get("partitionKey") is not None
            or item.get("partitionKeyOpaque") is True
        ):
            continue
        if not isinstance(item.get("session"), bool) or (
            item["session"] is False and item.get("expires") is None
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED)
        expiry = None if item["session"] is True else item.get("expires")
        try:
            cookie = ProtectedCookie.model_validate(
                {
                    "name": item.get("name"),
                    "value": item.get("value"),
                    "path": item.get("path"),
                    "http_only": item.get("httpOnly"),
                    "same_site": item.get("sameSite"),
                    "expires": expiry,
                },
                strict=True,
            )
        except ValidationError:
            raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED) from None
        if cookie.expires is not None and cookie.expires <= now:
            continue
        total += len(cookie.model_dump_json().encode("utf-8"))
        if total > MAX_SESSION_BYTES or len(chosen) >= MAX_SESSION_COOKIES:
            raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED)
        chosen.append(cookie)
    if not chosen:
        raise BrowserContinuationRefused(BrowserContinuationReason.COOKIE_MISSING)
    return tuple(chosen)


def protected_cookie_params(state: ProtectedSignIn) -> list[dict[str, JsonValue]]:
    """Restore using URL-derived host-only scope; never copy a page's domain parameter."""
    try:
        # Revalidate even an in-process model_copy/model_construct before the
        # native boundary. SDK TypedDicts describe requests; they do not validate them.
        state = ProtectedSignIn.model_validate(state, strict=True)
    except ValidationError:
        raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED) from None
    result: list[dict[str, JsonValue]] = []
    for cookie in state.cookies:
        item: dict[str, JsonValue] = {
            "url": state.provenance.origin + "/",
            "name": cookie.name.get_secret_value(),
            "value": cookie.value.get_secret_value(),
            "path": cookie.path.get_secret_value(),
            "secure": True,
            "httpOnly": cookie.http_only,
        }
        if cookie.same_site is not None:
            item["sameSite"] = cookie.same_site
        if cookie.expires is not None:
            item["expires"] = min(cookie.expires, state.provenance.expires_at.timestamp())
        result.append(item)
    if len(json.dumps(result).encode("utf-8")) > MAX_SESSION_BYTES + 4096:
        raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED)
    return result
