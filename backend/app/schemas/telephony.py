"""Telephone routing, consent and call receipts; credentials stay on the SMS bot."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.base import BaseSchema


class PhoneEndpointConfig(BaseSchema):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    inbound_embed_id: UUID | None = None
    max_call_seconds: int = Field(default=300, ge=60, le=900)
    calls_per_hour: int = Field(default=10, ge=1, le=120)
    calls_per_day: int = Field(default=30, ge=1, le=1000)
    max_concurrent: int = Field(default=2, ge=1, le=10)
    daily_budget_usd: Decimal = Field(default=Decimal("5"), gt=0, le=1000, decimal_places=6)
    price_per_minute_usd: Decimal = Field(
        gt=0,
        le=10,
        decimal_places=6,
        description="Operator's conservative per-leg telephony rate; model budgets apply separately.",
    )
    transfer_contact_ids: list[UUID] = Field(default_factory=list, max_length=20)


class PhoneEndpointRead(PhoneEndpointConfig):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    bot_id: UUID
    bot_name: str
    inbound_url: str
    status_url: str


class PhoneContactConfig(BaseSchema):
    model_config = ConfigDict(extra="forbid")
    identity_id: UUID
    allow_calls: bool = False
    allow_reports: bool = False
    allow_transfers: bool = False
    agent_ids: list[UUID] = Field(default_factory=list, max_length=100)
    allow_important: bool = False
    importance_instructions: str = Field(default="", max_length=1200)
    escalation_delay_seconds: int = Field(default=0, ge=0, le=86400)
    report_language: Literal["en-US", "pl-PL", "de-DE", "es-ES"] = "en-US"
    timezone: str = Field(default="UTC", max_length=64)
    quiet_start_hour: int = Field(default=22, ge=0, le=23)
    quiet_end_hour: int = Field(default=8, ge=0, le=23)
    calls_per_day: int = Field(default=3, ge=1, le=20)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Choose an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def distinct_hours(self) -> Self:
        if self.allow_important and (
            not self.agent_ids or not self.importance_instructions.strip()
        ):
            raise ValueError(
                "Important-case calls need selected agents and explicit importance criteria"
            )
        if self.quiet_start_hour == self.quiet_end_hour:
            raise ValueError("Quiet hours need a nonempty interval")
        return self


class PhoneContactRead(PhoneContactConfig):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    masked_number: str


class PhoneChoice(BaseSchema):
    id: UUID
    label: str


class PhoneSettingsRead(BaseSchema):
    endpoints: list[PhoneEndpointRead]
    contact: PhoneContactRead | None
    sms_identities: list[PhoneChoice]
    sms_bots: list[PhoneChoice]
    public_voice_embeds: list[PhoneChoice]
    transfer_contacts: list[PhoneChoice]
    call_endpoints: list[PhoneChoice]


class PhoneCallCreate(BaseSchema):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    endpoint_id: UUID
    agent_id: UUID | None = None
    mode: Literal["conversation", "report"] = "conversation"
    report: str | None = Field(default=None, min_length=1, max_length=5000)
    source_conversation_id: UUID | None = None
    outcome_id: UUID | None = None
    importance_reason: str | None = Field(default=None, min_length=1, max_length=1200)

    @model_validator(mode="after")
    def selected_mode(self) -> Self:
        if (self.outcome_id is None) != (self.importance_reason is None):
            raise ValueError("Important-case contact needs its shared outcome and assessment")
        if (self.mode == "report") != (self.report is not None):
            raise ValueError("A spoken report needs report text; a conversation does not")
        if self.mode == "conversation" and self.agent_id is None:
            raise ValueError("Choose an agent for a telephone conversation")
        return self


class PhoneCallRead(BaseSchema):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    endpoint_id: UUID
    purpose: str
    outcome_id: UUID | None
    not_before: datetime | None
    mode: str
    direction: str
    status: str
    conversation_id: UUID | None
    voice_call_id: UUID | None
    end_reason: str | None = None
    estimated_cost_usd: Decimal
    created_at: datetime


class PhoneTransfer(BaseSchema):
    contact_id: UUID


class TwilioCallReceipt(BaseModel):
    sid: str = Field(pattern=r"^CA[0-9a-fA-F]{32}$")
    account_sid: str = Field(pattern=r"^AC[0-9a-fA-F]{32}$")
    status: str


class PhoneCallsConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    endpoint_id: UUID = Field(
        title="Telephone endpoint",
        description="The configured Twilio telephone endpoint from Channels. Only explicit member consent and current limits authorize a call.",
    )
