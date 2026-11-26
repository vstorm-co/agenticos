"""Safe account identity and passive quota observations from CLIProxyAPI 8."""

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, TypeAdapter, ValidationError

from .contracts import AccountUsage, UsageWindow

logger = logging.getLogger(__name__)


class _Observation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    observed_at: AwareDatetime
    signals: dict[str, str]


def account_prefix(scope: str, name: str) -> str:
    """An opaque account route, bound to this person and organization."""
    return "account-" + hashlib.sha256(f"{scope}:{name}".encode()).hexdigest()[:24]


def account_usage(provider: str, raw: object, *, now: datetime | None = None) -> AccountUsage:
    """Expose reported windows only; missing observations never mean unused quota.

    CLIProxyAPI's credential `quota` is a passive snapshot from provider response
    headers. It is not a live billing probe. Do not infer limits for other vendors.
    """
    if provider not in {"codex", "claude", "devin"} or raw is None:
        return AccountUsage()
    try:
        observation = _Observation.model_validate(raw)
        signals = {key.lower(): value for key, value in observation.signals.items()}
        windows: list[UsageWindow] = []
        if provider == "devin":
            for window, minutes in (("daily", 1440), ("weekly", 10080)):
                remaining = signals.get(f"{window}_quota_remaining_percent")
                if remaining is None:
                    continue
                reset = signals.get(f"{window}_quota_reset_at")
                windows.append(
                    UsageWindow(
                        kind="provider",
                        remaining_percent=float(remaining.removesuffix("%")),
                        duration_minutes=minutes,
                        resets_at=TypeAdapter(AwareDatetime).validate_python(reset)
                        if reset is not None
                        else None,
                    )
                )
        else:
            kinds: tuple[Literal["primary", "secondary", "five_hour", "seven_day"], ...] = (
                ("primary", "secondary") if provider == "codex" else ("five_hour", "seven_day")
            )
            for kind in kinds:
                if provider == "codex":
                    prefix = f"x-codex-{kind}-"
                    used = signals.get(prefix + "used-percent")
                    duration = signals.get(prefix + "window-minutes")
                    reset = signals.get(prefix + "reset-at")
                    scale = 1
                else:
                    window = "5h" if kind == "five_hour" else "7d"
                    prefix = f"anthropic-ratelimit-unified-{window}-"
                    used = signals.get(prefix + "utilization")
                    duration = "300" if window == "5h" else "10080"
                    reset = signals.get(prefix + "reset")
                    scale = 100
                if used is None:
                    continue
                # Codex reports a disabled secondary window with a zero duration.
                # It must not discard the active primary window.
                if duration is not None and int(duration) == 0:
                    continue
                percentage = float(used) * scale
                windows.append(
                    UsageWindow(
                        kind=kind,
                        remaining_percent=100 - percentage,
                        duration_minutes=int(duration) if duration is not None else None,
                        resets_at=datetime.fromtimestamp(float(reset), UTC)
                        if reset is not None
                        else None,
                    )
                )
    except ValidationError, ValueError, OverflowError:
        logger.warning("The %s account quota observation could not be read", provider)
        return AccountUsage()
    if not windows:
        return AccountUsage(observed_at=observation.observed_at)
    reference = now or datetime.now(UTC)
    stale = reference - observation.observed_at > timedelta(minutes=5) or any(
        window.resets_at is not None and window.resets_at <= reference for window in windows
    )
    return AccountUsage(
        status="stale" if stale else "available",
        observed_at=observation.observed_at,
        windows=windows,
    )
