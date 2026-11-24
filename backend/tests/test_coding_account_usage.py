"""Provider usage snapshots preserve unknown telemetry instead of guessing."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.coding_account import (
    ProviderUsageSnapshot,
    ProviderUsageWindow,
    UsageReasonCode,
    UsageStatus,
    unavailable_provider_usage,
)

STATUSES: tuple[tuple[UsageStatus, UsageReasonCode], ...] = (
    ("rate_limited", "provider_reported_rate_limit"),
    ("authentication_required", "provider_authentication_required"),
    ("busy", "provider_busy"),
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
OBSERVED = NOW - timedelta(seconds=30)
VALID_UNTIL = NOW + timedelta(minutes=1)


def test_reported_usage_values_require_an_explicit_unit() -> None:
    with pytest.raises(ValidationError, match="explicit unit"):
        ProviderUsageWindow(name="requests", used=4)


def test_usage_snapshot_keeps_explicit_limits_and_age() -> None:
    result = ProviderUsageSnapshot.normalize(
        status="available",
        source="provider_api",
        observed_at=OBSERVED,
        valid_until=VALID_UNTIL,
        windows=[ProviderUsageWindow(name="requests", used=4, limit=10, unit="requests")],
        now=NOW,
    )

    assert result.status == "available"
    assert result.observation_age_seconds == 30
    assert result.windows[0].unit == "requests"


def test_missing_telemetry_stays_unknown() -> None:
    result = ProviderUsageSnapshot.normalize(
        status="available",
        source="unavailable",
        observed_at=OBSERVED,
        valid_until=VALID_UNTIL,
        windows=None,
        now=NOW,
    )

    assert result.status == "unknown"
    assert result.source == "unavailable"
    assert result.observed_at is None and result.windows == []
    assert result.reason_code == "telemetry_unavailable"


@pytest.mark.parametrize(
    ("observed_at", "valid_until", "reason"),
    [
        (None, VALID_UNTIL, "missing_observation_window"),
        (OBSERVED, None, "missing_observation_window"),
        (
            datetime(2026, 11, 16, 11, 59, tzinfo=UTC).replace(tzinfo=None),
            VALID_UNTIL,
            "invalid_observation_timezone",
        ),
        (
            OBSERVED,
            datetime(2026, 11, 16, 12, 1, tzinfo=UTC).replace(tzinfo=None),
            "invalid_validity_timezone",
        ),
        (NOW + timedelta(seconds=61), VALID_UNTIL, "clock_skew"),
        (OBSERVED - timedelta(minutes=2), NOW, "stale_observation"),
        (NOW + timedelta(seconds=30), NOW + timedelta(seconds=20), "stale_observation"),
    ],
)
def test_invalid_or_stale_observations_stay_unknown(
    observed_at: datetime | None,
    valid_until: datetime | None,
    reason: str,
) -> None:
    result = ProviderUsageSnapshot.normalize(
        status="available",
        source="provider_api",
        observed_at=observed_at,
        valid_until=valid_until,
        windows=[ProviderUsageWindow(name="requests", limit=10, unit="requests")],
        now=NOW,
    )

    assert result.status == "unknown"
    assert result.reason_code == reason
    assert result.windows == []


def test_missing_usage_windows_stay_unknown() -> None:
    result = ProviderUsageSnapshot.normalize(
        status="available",
        source="provider_api",
        observed_at=OBSERVED,
        valid_until=VALID_UNTIL,
        windows=None,
        now=NOW,
    )

    assert result.status == "unknown"
    assert result.reason_code == "usage_windows_unavailable"


@pytest.mark.parametrize(("status", "reason"), STATUSES)
def test_provider_status_without_a_usage_window_is_preserved(
    status: UsageStatus, reason: UsageReasonCode
) -> None:
    result = ProviderUsageSnapshot.normalize(
        status=status,
        source="native_runtime",
        observed_at=OBSERVED,
        valid_until=VALID_UNTIL,
        windows=None,
        reason_code=reason,
        now=NOW,
    )

    assert result.status == status
    assert result.windows == []
    assert result.reason_code == reason


def test_small_clock_skew_is_clamped_to_zero_age() -> None:
    result = ProviderUsageSnapshot.normalize(
        status="available",
        source="provider_api",
        observed_at=NOW + timedelta(seconds=30),
        valid_until=VALID_UNTIL,
        windows=[ProviderUsageWindow(name="requests", limit=10, unit="requests")],
        now=NOW,
    )

    assert result.status == "available"
    assert result.observation_age_seconds == 0


def test_unavailable_provider_usage_is_explicitly_unverified() -> None:
    result = unavailable_provider_usage()

    assert result.status == "unknown"
    assert result.source == "unavailable"
    assert result.reason_code == "provider_contract_unverified"


def test_naive_current_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        ProviderUsageSnapshot.normalize(
            status="available",
            source="provider_api",
            observed_at=OBSERVED,
            valid_until=VALID_UNTIL,
            windows=[],
            now=NOW.replace(tzinfo=None),
        )
