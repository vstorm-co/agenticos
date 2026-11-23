"""Read subscription quota metadata through the credential-owning process.

Only fixed provider quota URLs are reachable here. CLIProxyAPI substitutes the
account token inside its process; neither tokens nor provider responses leave
this adapter. No inference request is made.
"""

import json
import re
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import AliasChoices, AwareDatetime, BaseModel, Field, ValidationError

from ._instances import GatewayError, Instance
from .contracts import AccountUsage, UsageWindow


class _Reply(BaseModel):
    status_code: int
    body: str = Field(max_length=1_000_000)


class _Project(BaseModel):
    project: str | None = Field(default=None, alias="cloudaicompanionProject", max_length=256)


class _Bucket(BaseModel):
    window: str = Field(default="", max_length=120)
    label: str = Field(default="", alias="displayName", max_length=120)
    remaining: float | None = Field(
        default=None, alias="remainingFraction", ge=0, le=1, allow_inf_nan=False
    )
    resets_at: AwareDatetime | None = Field(default=None, alias="resetTime")
    disabled: bool = False


class _Group(BaseModel):
    label: str = Field(default="", alias="displayName", max_length=120)
    buckets: list[_Bucket] = Field(default_factory=list, max_length=32)


class _Summary(BaseModel):
    groups: list[_Group] = Field(default_factory=list, max_length=32)


async def _call(
    client: httpx.AsyncClient,
    instance: Instance,
    auth_index: str,
    url: str,
    body: dict[str, str],
    *,
    method: Literal["GET", "POST"] = "POST",
    account_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> str:
    response = await client.post(
        f"{instance.base_url}/v8/management/requests/api-call",
        headers={"Authorization": f"Bearer {instance.management_key}"},
        json={
            "auth_index": auth_index,
            "method": method,
            "url": url,
            "header": {
                "Authorization": "Bearer $TOKEN$",
                "Content-Type": "application/json",
                "User-Agent": "AgenticOS",
                **({"ChatGPT-Account-Id": account_id} if account_id is not None else {}),
                **(extra_headers or {}),
            },
            "data": json.dumps(body) if method == "POST" else "",
        },
    )
    response.raise_for_status()
    reply = _Reply.model_validate_json(response.content)
    if not 200 <= reply.status_code < 300:
        raise GatewayError("The provider did not return subscription limits", status=502)
    return reply.body


def _duration(label: str) -> int | None:
    label = label.lower()
    if "week" in label:
        return 10080
    if "day" in label or "daily" in label:
        return 1440
    hours = re.search(r"\b(\d+)\s*[-_ ]?\s*(?:h\b|hours?\b)", label)
    return int(hours[1]) * 60 if hours and int(hours[1]) > 0 else None


async def antigravity_usage(instance: Instance, auth_index: str) -> AccountUsage:
    """Fetch each provider-reported quota group, keeping its windows distinct."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            project = _Project.model_validate_json(
                await _call(
                    client,
                    instance,
                    auth_index,
                    "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
                    {},
                )
            )
            if not project.project:
                return AccountUsage()
            summary = _Summary.model_validate_json(
                await _call(
                    client,
                    instance,
                    auth_index,
                    "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary",
                    {"project": project.project},
                )
            )
    except httpx.HTTPError, ValidationError:
        raise GatewayError("Subscription limits could not be read; try again", status=502) from None
    now = datetime.now(UTC)
    windows = [
        UsageWindow(
            kind="provider",
            label=" · ".join(part for part in (group.label, bucket.label or bucket.window) if part)
            or None,
            remaining_percent=bucket.remaining * 100,
            duration_minutes=_duration(bucket.window + " " + bucket.label),
            resets_at=bucket.resets_at,
        )
        for group in summary.groups
        for bucket in group.buckets
        if bucket.remaining is not None and not bucket.disabled
    ]
    return AccountUsage(
        status="unavailable"
        if not windows
        else "stale"
        if any(window.resets_at is not None and window.resets_at <= now for window in windows)
        else "available",
        observed_at=now,
        windows=windows,
    )


class _CodexWindow(BaseModel):
    used_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    limit_window_seconds: int | None = Field(default=None, ge=0)
    reset_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class _CodexLimits(BaseModel):
    primary_window: _CodexWindow | None = None
    secondary_window: _CodexWindow | None = None


class _CodexUsage(BaseModel):
    rate_limit: _CodexLimits | None = None


async def codex_usage(instance: Instance, auth_index: str, account_id: str) -> AccountUsage:
    """Read the account's ChatGPT usage windows without waiting for a model response."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            usage = _CodexUsage.model_validate_json(
                await _call(
                    client,
                    instance,
                    auth_index,
                    "https://chatgpt.com/backend-api/wham/usage",
                    {},
                    method="GET",
                    account_id=account_id,
                )
            )
        limits = usage.rate_limit
        windows: list[UsageWindow] = []
        if limits is not None:
            named: tuple[tuple[Literal["primary", "secondary"], _CodexWindow | None], ...] = (
                ("primary", limits.primary_window),
                ("secondary", limits.secondary_window),
            )
            for kind, window in named:
                if (
                    window is None
                    or window.used_percent is None
                    or window.limit_window_seconds == 0
                ):
                    continue
                windows.append(
                    UsageWindow(
                        kind=kind,
                        remaining_percent=100 - window.used_percent,
                        duration_minutes=(window.limit_window_seconds + 59) // 60
                        if window.limit_window_seconds
                        else None,
                        resets_at=datetime.fromtimestamp(window.reset_at, UTC)
                        if window.reset_at is not None
                        else None,
                    )
                )
    except httpx.HTTPError, ValidationError, ValueError, OverflowError:
        raise GatewayError("Subscription limits could not be read; try again", status=502) from None
    now = datetime.now(UTC)
    return AccountUsage(
        status="unavailable"
        if not windows
        else "stale"
        if any(window.resets_at is not None and window.resets_at <= now for window in windows)
        else "available",
        observed_at=now,
        windows=windows,
    )


class _ClaudeWindow(BaseModel):
    utilization: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    resets_at: AwareDatetime | None = None


class _ClaudeModel(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)


class _ClaudeScope(BaseModel):
    model: _ClaudeModel | None = None


class _ClaudeLimit(BaseModel):
    kind: str = Field(max_length=64)
    percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    resets_at: AwareDatetime | None = None
    scope: _ClaudeScope | None = None


class _ClaudeUsage(BaseModel):
    five_hour: _ClaudeWindow | None = None
    seven_day: _ClaudeWindow | None = None
    seven_day_opus: _ClaudeWindow | None = None
    seven_day_sonnet: _ClaudeWindow | None = None
    seven_day_fable: _ClaudeWindow | None = None
    limits: list[_ClaudeLimit] | None = Field(default=None, max_length=64)


async def claude_usage(instance: Instance, auth_index: str) -> AccountUsage:
    """Read OAuth quota metadata, including both named and scoped usage windows."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            usage = _ClaudeUsage.model_validate_json(
                await _call(
                    client,
                    instance,
                    auth_index,
                    "https://api.anthropic.com/api/oauth/usage",
                    {},
                    method="GET",
                    extra_headers={"anthropic-beta": "oauth-2025-04-20"},
                )
            )
    except httpx.HTTPError, ValidationError:
        raise GatewayError("Subscription limits could not be read; try again", status=502) from None
    windows: list[UsageWindow] = []
    if usage.limits is not None:
        for limit in usage.limits:
            if limit.percent is None or limit.kind not in {
                "session",
                "weekly_all",
                "weekly_scoped",
            }:
                continue
            family = limit.scope.model if limit.scope is not None else None
            windows.append(
                UsageWindow(
                    kind="five_hour"
                    if limit.kind == "session"
                    else "seven_day"
                    if limit.kind == "weekly_all"
                    else "provider",
                    label=family.display_name if family is not None else None,
                    remaining_percent=100 - limit.percent,
                    duration_minutes=300 if limit.kind == "session" else 10080,
                    resets_at=limit.resets_at,
                )
            )
    else:
        legacy: tuple[tuple[str | None, _ClaudeWindow | None], ...] = (
            (None, usage.five_hour),
            (None, usage.seven_day),
            ("Opus", usage.seven_day_opus),
            ("Sonnet", usage.seven_day_sonnet),
            ("Fable", usage.seven_day_fable),
        )
        for index, (label, window) in enumerate(legacy):
            if window is None or window.utilization is None:
                continue
            windows.append(
                UsageWindow(
                    kind="five_hour" if index == 0 else "seven_day" if index == 1 else "provider",
                    label=label,
                    remaining_percent=100 - window.utilization,
                    duration_minutes=300 if index == 0 else 10080,
                    resets_at=window.resets_at,
                )
            )
    now = datetime.now(UTC)
    return AccountUsage(
        status="unavailable"
        if not windows
        else "stale"
        if any(window.resets_at is not None and window.resets_at <= now for window in windows)
        else "available",
        observed_at=now,
        windows=windows,
    )


class _KimiQuota(BaseModel):
    limit: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    used: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    remaining: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    resets_at: AwareDatetime | None = Field(
        default=None,
        validation_alias=AliasChoices("reset_at", "resetAt", "reset_time", "resetTime"),
    )
    name: str | None = Field(default=None, max_length=120)


class _KimiPeriod(BaseModel):
    duration: int = Field(gt=0)
    time_unit: str = Field(alias="timeUnit", max_length=32)


class _KimiLimit(_KimiQuota):
    detail: _KimiQuota | None = None
    window: _KimiPeriod | None = None


class _KimiUsage(BaseModel):
    usage: _KimiQuota | None = None
    limits: list[_KimiLimit] = Field(default_factory=list, max_length=64)


def _kimi_window(quota: _KimiQuota, duration: int | None, label: str | None) -> UsageWindow | None:
    if not quota.limit:
        return None
    if quota.remaining is not None:
        remaining = quota.remaining
    elif quota.used is not None:
        remaining = quota.limit - quota.used
    else:
        return None
    return UsageWindow(
        kind="provider",
        label=label,
        remaining_percent=100 * remaining / quota.limit,
        duration_minutes=duration,
        resets_at=quota.resets_at,
    )


async def kimi_usage(instance: Instance, auth_index: str, *, international: bool) -> AccountUsage:
    """Read Kimi Code weekly and rolling windows from its selected regional issuer."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            usage = _KimiUsage.model_validate_json(
                await _call(
                    client,
                    instance,
                    auth_index,
                    "https://api.kimi.ai/coding/v1/usages"
                    if international
                    else "https://api.kimi.com/coding/v1/usages",
                    {},
                    method="GET",
                )
            )
        windows: list[UsageWindow] = []
        if usage.usage is not None:
            weekly = _kimi_window(usage.usage, 10080, usage.usage.name)
            if weekly is not None:
                windows.append(weekly)
        for limit in usage.limits:
            duration = None
            if limit.window is not None:
                unit = limit.window.time_unit.upper().removeprefix("TIME_UNIT_").removesuffix("S")
                factor = {"MINUTE": 60, "HOUR": 3600, "DAY": 86400, "SECOND": 1}.get(unit)
                if factor is not None:
                    duration = (limit.window.duration * factor + 59) // 60
            quota = limit.detail or limit
            window = _kimi_window(quota, duration, limit.name or quota.name)
            if window is not None:
                windows.append(window)
    except httpx.HTTPError, ValidationError:
        raise GatewayError("Subscription limits could not be read; try again", status=502) from None
    now = datetime.now(UTC)
    return AccountUsage(
        status="unavailable"
        if not windows
        else "stale"
        if any(window.resets_at is not None and window.resets_at <= now for window in windows)
        else "available",
        observed_at=now,
        windows=windows,
    )
