"""Account routes and provider-observed quota windows never imply free quota."""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.subscription_gateway._account_data import account_prefix, account_usage

NOW = datetime(2026, 11, 21, 22, 0, tzinfo=UTC)


def test_account_routes_do_not_reveal_identity_or_cross_scopes() -> None:
    route = account_prefix("alice", "me@example.com.json")
    assert route.startswith("account-") and len(route) == 32
    assert route == account_prefix("alice", "me@example.com.json")
    assert route != account_prefix("bob", "me@example.com.json")
    assert "example" not in route


def test_codex_windows_use_reported_durations_and_reset_times() -> None:
    usage = account_usage(
        "codex",
        {
            "observed_at": NOW.isoformat(),
            "signals": {
                "X-Codex-Primary-Used-Percent": "61",
                "X-Codex-Primary-Window-Minutes": "10080",
                "X-Codex-Primary-Reset-At": str((NOW + timedelta(days=2)).timestamp()),
                "X-Codex-Secondary-Used-Percent": "0",
            },
        },
        now=NOW,
    )
    assert usage.status == "available"
    assert usage.windows[0].remaining_percent == 39
    assert usage.windows[0].duration_minutes == 10080
    assert usage.windows[0].resets_at == NOW + timedelta(days=2)
    assert usage.windows[1].remaining_percent == 100
    assert usage.windows[1].duration_minutes is None
    assert usage.windows[1].resets_at is None


def test_claude_reports_separate_five_hour_and_weekly_windows() -> None:
    usage = account_usage(
        "claude",
        {
            "observed_at": NOW.isoformat(),
            "signals": {
                "anthropic-ratelimit-unified-5h-utilization": "0.5",
                "anthropic-ratelimit-unified-7d-utilization": "1",
            },
        },
        now=NOW,
    )
    assert [(w.remaining_percent, w.duration_minutes) for w in usage.windows] == [
        (50, 300),
        (0, 10080),
    ]


@pytest.mark.parametrize(
    "provider,raw",
    [
        ("antigravity", {}),
        ("codex", None),
        ("codex", {}),
        ("codex", {"observed_at": "2026-11-21T22:00:00", "signals": {}}),
        ("codex", {"observed_at": NOW.isoformat(), "signals": {}}),
    ],
)
def test_missing_or_unsupported_observations_are_unavailable(provider: str, raw: object) -> None:
    usage = account_usage(provider, raw, now=NOW)
    assert usage.status == "unavailable" and usage.windows == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("used-percent", "NaN"),
        ("used-percent", "-1"),
        ("used-percent", "101"),
        ("used-percent", "broken"),
        ("window-minutes", "0"),
        ("window-minutes", "broken"),
        ("reset-at", "NaN"),
        ("reset-at", "1e99"),
    ],
)
def test_malformed_observations_never_become_available_quota(field: str, value: str) -> None:
    signals = {"x-codex-primary-used-percent": "50", f"x-codex-primary-{field}": value}
    usage = account_usage("codex", {"observed_at": NOW.isoformat(), "signals": signals}, now=NOW)
    assert usage.status == "unavailable" and not usage.windows


@pytest.mark.parametrize("age,reset", [(6, None), (0, NOW.timestamp())])
def test_old_or_expired_windows_are_explicitly_stale(age: int, reset: float | None) -> None:
    signals = {"x-codex-primary-used-percent": "25"}
    if reset is not None:
        signals["x-codex-primary-reset-at"] = str(reset)
    usage = account_usage(
        "codex",
        {"observed_at": (NOW - timedelta(minutes=age)).isoformat(), "signals": signals},
        now=NOW,
    )
    assert usage.status == "stale"


def test_observations_can_be_dated_against_the_current_clock() -> None:
    usage = account_usage(
        "codex",
        {
            "observed_at": datetime.now(UTC).isoformat(),
            "signals": {"x-codex-secondary-used-percent": "10"},
        },
    )
    assert usage.status == "available"


def test_gateway_wire_contract_is_independent_of_backend_settings(tmp_path: Path) -> None:
    source = "import sys; from app.subscription_gateway._server import create_app; assert 'app.core.config' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
