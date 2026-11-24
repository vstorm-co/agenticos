"""Value-free contracts shared by the API and the one live browser writer."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.browser_origins import browser_origin
from app.core.exceptions import BadRequestError

BrowserFillField = Literal[
    "username",
    "password",
    "totp",
    "name",
    "email",
    "phone",
    "address_line1",
    "address_line2",
    "city",
    "region",
    "postal_code",
    "country",
]


class BrowserFillOperation(StrEnum):
    FILL = "fill"
    SUBMIT = "submit"


class BrowserFillState(StrEnum):
    REQUESTED = "requested"
    PREPARING = "preparing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPROVED = "approved"
    CLAIMED = "claimed"
    FILLED = "filled"
    SUBMITTED = "submitted"
    REFUSED = "refused"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    DECLINED = "declined"


ACTIVE_FILL_STATES = frozenset(
    {
        BrowserFillState.REQUESTED,
        BrowserFillState.PREPARING,
        BrowserFillState.AWAITING_CONFIRMATION,
        BrowserFillState.APPROVED,
        BrowserFillState.CLAIMED,
    }
)


class BrowserFillReason(StrEnum):
    DISABLED = "fill_disabled"
    NOT_AVAILABLE = "credential_unavailable"
    LIVE_BROWSER_REQUIRED = "live_browser_required"
    OWNERSHIP_LOST = "browser_ownership_lost"
    DOCUMENT_CHANGED = "document_changed"
    DESTINATION_REFUSED = "destination_refused"
    FIELD_REFUSED = "field_refused"
    AUTHORITY_CHANGED = "authority_changed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_EXPIRED = "confirmation_expired"
    CONFIRMATION_DECLINED = "confirmation_declined"
    PROTECTION_UNAVAILABLE = "output_protection_unavailable"
    PROVIDER_UNAVAILABLE = "browser_unavailable"
    UNCERTAIN_EFFECT = "uncertain_fill_effect"
    ALREADY_CONSUMED = "plan_already_consumed"
    TOTP_WINDOW = "totp_window_unavailable"


class BrowserFillRefused(BadRequestError):
    """A fixed refusal code; native errors and submitted values never become messages."""

    def __init__(self, reason: BrowserFillReason) -> None:
        self.reason = reason
        super().__init__(
            message="Browser credential operation refused", details={"reason_code": reason.value}
        )


class BrowserFillTarget(BaseModel):
    """An existing numbered element, never a selector, URL or script from a caller."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    field: BrowserFillField
    element_id: int = Field(ge=0, le=200)


class BrowserFillSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    fields: tuple[BrowserFillTarget, ...] = Field(min_length=1, max_length=9)

    @model_validator(mode="after")
    def _one_destination_for_each_field(self) -> BrowserFillSelection:
        if len({item.field for item in self.fields}) != len(self.fields) or len(
            {item.element_id for item in self.fields}
        ) != len(self.fields):
            raise ValueError("Select each credential field and page element only once")
        return self


class BrowserFillHandle(BaseModel):
    """A reference to one element kept in the owning page's isolated context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: BrowserFillField
    handle: UUID
    role: Literal["text", "password", "email", "tel", "textarea", "select"]
    form_origin: str

    @field_validator("form_origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return browser_origin(value)


class BrowserFillObservation(BaseModel):
    """Only identities and reviewed field roles survive native preparation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: UUID
    origin: str
    fields: tuple[BrowserFillHandle, ...] = Field(min_length=1, max_length=9)

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        return browser_origin(value)

    @model_validator(mode="after")
    def _same_origin_and_distinct_handles(self) -> BrowserFillObservation:
        if (
            any(item.form_origin != self.origin for item in self.fields)
            or len({item.handle for item in self.fields}) != len(self.fields)
            or len({item.field for item in self.fields}) != len(self.fields)
        ):
            raise ValueError("A fill requires distinct fields at one exact destination")
        return self
