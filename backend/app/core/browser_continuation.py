"""Closed, value-free contracts for a credential-derived protected browser session."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.browser_origins import browser_origin
from app.core.exceptions import BadRequestError


class BrowserContinuationState(StrEnum):
    REQUESTED = "requested"
    PREPARING = "preparing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPROVED = "approved"
    CLAIMED = "claimed"
    CONTINUED = "continued"
    REFUSED = "refused"
    EXPIRED = "expired"
    DECLINED = "declined"
    UNKNOWN = "unknown"


ACTIVE_CONTINUATION_STATES = frozenset(
    {
        BrowserContinuationState.REQUESTED,
        BrowserContinuationState.PREPARING,
        BrowserContinuationState.AWAITING_CONFIRMATION,
        BrowserContinuationState.APPROVED,
        BrowserContinuationState.CLAIMED,
    }
)


class BrowserContinuationReason(StrEnum):
    DISABLED = "continuation_disabled"
    NOT_AVAILABLE = "continuation_unavailable"
    SOURCE_NOT_SUBMITTED = "source_not_submitted"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_EXPIRED = "confirmation_expired"
    DOCUMENT_CHANGED = "document_changed"
    DESTINATION_REFUSED = "destination_refused"
    AUTHORITY_CHANGED = "authority_changed"
    OWNERSHIP_LOST = "browser_ownership_lost"
    PROTECTION_UNAVAILABLE = "output_protection_unavailable"
    STATE_REFUSED = "session_state_refused"
    COOKIE_MISSING = "session_cookie_missing"
    PROVIDER_UNAVAILABLE = "browser_unavailable"
    UNCERTAIN_EFFECT = "uncertain_continuation"
    ALREADY_CONSUMED = "continuation_already_consumed"


class BrowserContinuationRefused(BadRequestError):
    """Native responses, cookie values and page errors never become refusal text."""

    def __init__(self, reason: BrowserContinuationReason) -> None:
        self.reason = reason
        super().__init__(
            message="Browser session continuation refused", details={"reason_code": reason.value}
        )


def require_continuation(condition: bool, reason: BrowserContinuationReason) -> None:
    """Keep fixed refusals outside cleanup handlers that must catch every native failure."""
    if not condition:
        raise BrowserContinuationRefused(reason)


class BrowserContinuationObservation(BaseModel):
    """A server-owned identity for the current document after native submission."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    document_id: UUID
    origin: str

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return browser_origin(value)
