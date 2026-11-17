"""Browser teaching capture contracts: what one stored step may contain, and nothing else.

A step has an exact HTTPS origin, an action, and for a control a role plus a
hashed structural fingerprint. There is no field for a path, query, fragment,
typed value, page text, label, input name, cookie, screenshot or script, so
none of them can be stored by mistake. Validation errors never echo their
input, because the refused input may itself be a secret.
"""

import json
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.core.exceptions import BadRequestError, ConflictError

MAX_EVENTS = 500
MAX_EVENT_BYTES = 128 * 1024
MAX_CAPTURE_SECONDS = 30 * 60
RETENTION_SECONDS = 24 * 60 * 60
MAX_ORIGINS = 10

Action = Literal["navigate", "click", "select", "input_parameter", "scroll", "checkpoint"]
Role = Literal[
    "button",
    "link",
    "textbox",
    "combobox",
    "checkbox",
    "radio",
    "tab",
    "menuitem",
    "option",
    "switch",
]
CONTROL_ACTIONS = frozenset({"click", "select", "input_parameter"})


class TeachingState(StrEnum):
    RECORDING = "recording"
    PAUSED = "paused"
    REVIEW = "review"
    DISCARDED = "discarded"
    EXPIRED = "expired"


class TeachingReason(StrEnum):
    """Stable reason codes; the only detail a refusal or a paused row carries."""

    DISABLED = "teaching_disabled"
    UNAVAILABLE = "teaching_unavailable"
    NOT_HELD = "browser_not_held"
    OWNERSHIP_LOST = "browser_ownership_lost"
    AUTHORITY_CHANGED = "authority_changed"
    EXPIRED = "teaching_expired"
    EVENT_LIMIT = "event_limit_reached"
    BYTE_LIMIT = "event_bytes_limit_reached"
    TIME_LIMIT = "capture_time_limit_reached"
    AUTHENTICATION = "human_authentication_required"
    ORIGIN_REFUSED = "origin_not_allowed"
    CAPTURE_FAILED = "capture_unavailable"
    PAUSED_BY_OWNER = "paused_by_owner"
    STALE_REVISION = "stale_revision"
    EVENT_CONFLICT = "event_sequence_conflict"
    REQUEST_REUSED = "idempotency_key_reused"
    ALREADY_RECORDING = "teaching_already_active"
    WRONG_STATE = "invalid_transition"


class TeachingRefused(BadRequestError):
    def __init__(self, reason: TeachingReason) -> None:
        self.reason = reason
        super().__init__(message="Browser teaching refused", details={"reason_code": reason.value})


class TeachingConflict(ConflictError):
    def __init__(self, reason: TeachingReason) -> None:
        self.reason = reason
        super().__init__(message="Browser teaching conflict", details={"reason_code": reason.value})


def teaching_origin(value: str) -> str:
    """Normalize an exact HTTPS origin, or raise `ValueError` without repeating the input.

    Refuses anything that is more than an origin: userinfo, a path, a query, a
    fragment or a wildcard. The host is lower-cased and IDNA-encoded and the
    default port is dropped, so one site has one spelling.
    """
    refused = "Use an exact HTTPS origin such as https://portal.example.com"
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(char.isspace() or ord(char) < 32 or char in "*?#\\@" for char in value)
    ):
        raise ValueError(refused)
    try:
        parts = urlsplit(value)
        port = parts.port
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
    except ValueError, UnicodeError:
        raise ValueError(refused) from None
    if (
        parts.scheme != "https"
        or not host
        or parts.path not in ("", "/")
        or "." not in host.strip("[]")
    ):
        raise ValueError(refused)
    return f"https://{host}" + ("" if port in (None, 443) else f":{port}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class StructuralTarget(_Strict):
    role: Role
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class Observation(_Strict):
    """What the page observer may report about the page and the input's target."""

    origin: str
    target: StructuralTarget | None = None
    authentication: bool = False
    """The target or its form is a password, one-time-code or CAPTCHA control."""

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return teaching_origin(value)


class CapturedStep(_Strict):
    """One stored step. `input_id` is derived on the server from the hold and its input count."""

    sequence: int = Field(ge=1, le=MAX_EVENTS)
    input_id: UUID
    action: Action
    origin: str
    target: StructuralTarget | None = None
    direction: Literal["up", "down"] | None = None
    human_step: bool = False

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return teaching_origin(value)

    @model_validator(mode="after")
    def _consistent(self) -> CapturedStep:
        valid = (
            (self.action in CONTROL_ACTIONS) == (self.target is not None)
            and (self.action == "scroll") == (self.direction is not None)
            and (not self.human_step or self.action == "checkpoint")
        )
        if not valid:
            raise ValueError("Step fields do not match its action")
        return self


def encoded_size(steps: list[dict[str, JsonValue]]) -> int:
    """Bytes the stored step list takes, measured the way the database limit measures it."""
    return len(json.dumps(steps, separators=(", ", ": "), ensure_ascii=False).encode())


def revision_from_if_match(value: str | None) -> int | None:
    """The revision an `If-Match` header names (`3` or `"3"`), or `None` when it names none."""
    if value is None:
        return None
    text = value.strip().removeprefix("W/").strip('"')
    return int(text) if text.isdecimal() and len(text) <= 9 else None
