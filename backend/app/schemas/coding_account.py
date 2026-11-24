"""Only the owner sees coding-account metadata; credentials never leave the vault."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator

from app.schemas.base import BaseSchema

CodingHarness = Literal["claude_code", "codex"]
UsageStatus = Literal[
    "available",
    "busy",
    "rate_limited",
    "quota_exhausted",
    "capacity_unavailable",
    "authentication_required",
    "disabled",
    "unknown",
]
UsageSource = Literal["provider_api", "native_runtime", "unavailable"]
UsageReasonCode = Literal[
    "provider_contract_unverified",
    "telemetry_unavailable",
    "missing_observation_window",
    "invalid_observation_timezone",
    "invalid_validity_timezone",
    "clock_skew",
    "stale_observation",
    "usage_windows_unavailable",
    "provider_reported_rate_limit",
    "provider_authentication_required",
    "provider_capacity_unavailable",
    "provider_busy",
    "provider_identity_mismatch",
    "provider_readiness_unavailable",
    "provider_reported_quota_exhausted",
    "runtime_version_unsupported",
    "model_catalog_unverified",
    "telemetry_unsupported",
    "probe_timeout",
]
MAX_USAGE_CLOCK_SKEW_SECONDS = 60


class ProviderUsageWindow(BaseSchema):
    """One provider-reported limit; values keep the provider's explicit unit."""

    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    used: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    limit: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unit: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9_-]+$",
    )
    resets_at: datetime | None = None
    window_duration_minutes: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def values_have_a_unit(self) -> Self:
        if (self.used is not None or self.limit is not None) and self.unit is None:
            raise ValueError("Reported usage values require an explicit unit")
        return self


class ProviderUsageSnapshot(BaseSchema):
    """Read-only provider usage evidence; absent or stale evidence stays unknown."""

    status: UsageStatus = "unknown"
    observed_at: datetime | None = None
    observation_age_seconds: int | None = None
    valid_until: datetime | None = None
    source: UsageSource = "unavailable"
    windows: list[ProviderUsageWindow] = Field(default_factory=list)
    reason_code: UsageReasonCode | None = None

    @classmethod
    def normalize(
        cls,
        *,
        status: UsageStatus,
        source: UsageSource,
        observed_at: datetime | None,
        valid_until: datetime | None,
        windows: list[ProviderUsageWindow] | None,
        reason_code: UsageReasonCode | None = None,
        now: datetime | None = None,
    ) -> Self:
        """Normalize adapter evidence and reject stale, incomplete or skewed data."""
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("The current time must include a timezone")
        if source == "unavailable":
            return cls(reason_code=reason_code or "telemetry_unavailable")
        if observed_at is None or valid_until is None:
            return cls(reason_code="missing_observation_window")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return cls(reason_code="invalid_observation_timezone")
        if valid_until.tzinfo is None or valid_until.utcoffset() is None:
            return cls(reason_code="invalid_validity_timezone")

        age = int((current - observed_at).total_seconds())
        if age < -MAX_USAGE_CLOCK_SKEW_SECONDS:
            return cls(reason_code="clock_skew")
        if current >= valid_until or observed_at > valid_until:
            return cls(reason_code="stale_observation")
        normalized_windows = windows or []
        if status == "available" and not normalized_windows:
            return cls(reason_code="usage_windows_unavailable")
        return cls(
            status=status,
            observed_at=observed_at,
            observation_age_seconds=max(0, age),
            valid_until=valid_until,
            source=source,
            windows=normalized_windows,
            reason_code=reason_code,
        )


def unavailable_provider_usage() -> ProviderUsageSnapshot:
    """Return the honest state while no documented adapter is enabled."""
    return ProviderUsageSnapshot(reason_code="provider_contract_unverified")


ModelId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._:/-]{0,127}$")]


class ProviderModelCatalog(BaseSchema):
    """Models advertised by the selected account's provider; no per-call guarantee."""

    status: Literal["advertised", "unknown"] = "unknown"
    source: Literal["native_runtime", "unavailable"] = "unavailable"
    observed_at: datetime | None = None
    valid_until: datetime | None = None
    model_ids: list[ModelId] = Field(default_factory=list, max_length=200)
    reason_code: UsageReasonCode | None = "model_catalog_unverified"

    def fresh(self, now: datetime) -> Self:
        """A stale catalog cannot be presented as current provider advertisement."""
        if (
            self.status != "advertised"
            or self.source != "native_runtime"
            or not self.model_ids
            or self.observed_at is None
            or self.valid_until is None
            or self.observed_at.tzinfo is None
            or self.valid_until.tzinfo is None
            or self.observed_at > self.valid_until
            or (self.observed_at - now).total_seconds() > MAX_USAGE_CLOCK_SKEW_SECONDS
            or now >= self.valid_until
        ):
            return type(self)()
        return self


class CodingAccountUsageRead(BaseSchema):
    account_id: UUID
    generation: UUID
    usage: ProviderUsageSnapshot = Field(default_factory=unavailable_provider_usage)
    model_catalog: ProviderModelCatalog = Field(default_factory=ProviderModelCatalog)
    refresh_pending: bool = False


class CodingAccountUsageRefresh(BaseSchema):
    generation: UUID


class CodingAccountCreate(BaseSchema):
    harness: CodingHarness
    label: str = Field(min_length=1, max_length=120)
    api_key: SecretStr = Field(min_length=8, max_length=8192)
    enabled: bool = False

    @field_validator("api_key")
    @classmethod
    def complete_key(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() != value.get_secret_value().strip():
            raise ValueError("Remove whitespace around the credential")
        return value


class CodingAccountRead(BaseSchema):
    id: UUID
    harness: CodingHarness
    label: str
    secret_kind: Literal["api_key", "openai_codex"]
    enabled: bool
    generation: UUID
    is_default: bool
    pool_member: bool
    usage: ProviderUsageSnapshot = Field(default_factory=unavailable_provider_usage)
    model_catalog: ProviderModelCatalog = Field(default_factory=ProviderModelCatalog)
    usage_refresh_pending: bool = False


class CodingAccountList(BaseSchema):
    items: list[CodingAccountRead]


class CodingAccountUpdate(BaseSchema):
    generation: UUID
    enabled: bool
    is_default: Literal[True] | None = None
    pool_member: bool | None = None


class CodingAccountOAuthComplete(BaseSchema):
    label: str = Field(min_length=1, max_length=120)
    callback_url: SecretStr = Field(min_length=1, max_length=8192)
    enabled: bool = False


class CodingAccountOAuthStart(BaseSchema):
    authorization_url: str
