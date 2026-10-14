"""How long a call may run and whether it can be afforded (#54). Pure arithmetic."""

from decimal import Decimal

from app.services.realtime_models import RealtimeModelEntry

CALL_CEILING_SECONDS = 3000
"""50 minutes: below OpenAI's 60-minute hard stop, so our cap always lands first."""

MIN_CALL_SECONDS = 60
"""Less than a minute left is not worth starting a call for."""

WARN_SECONDS = 60
"""When the call view and the agent are told the end is near."""

HEARTBEAT_SECONDS = 15
"""How often the process holding a call proves it is still holding it."""

STALE_AFTER_SECONDS = 45
"""Three missed heartbeats: the reaper's threshold, and the concurrency count's."""

RESUME_WINDOW_SECONDS = 10
"""How soon after a connection ends a reconnect may continue its call (Q13)."""

RESUME_WAIT_SECONDS = 3.0
"""How long a reconnect waits for a half-open previous connection to finish ending."""


def call_cap_seconds(
    *, org_max: int, agent_max: int | None, chain_elapsed: int, minutes_left: int | None
) -> int:
    """The longest this connection may run: the tightest of every limit, never negative.

    `chain_elapsed` is what earlier connections of the same call already used -
    a reconnect continues a call, it does not restart its clock.
    """
    cap = min(org_max, CALL_CEILING_SECONDS)
    if agent_max is not None:
        cap = min(cap, agent_max)
    cap -= chain_elapsed
    if minutes_left is not None:
        cap = min(cap, minutes_left)
    return max(cap, 0)


def minutes_left_seconds(*, monthly_minutes: int | None, used_seconds: int) -> int | None:
    """Seconds left in this month's call minutes, or `None` when only budgets bind."""
    if monthly_minutes is None:
        return None
    return max(monthly_minutes * 60 - used_seconds, 0)


def worst_case_usd(*, cap_seconds: int, entry: RealtimeModelEntry) -> Decimal:
    """What the call could cost at the model's worst price per minute, for the setup check."""
    return (Decimal(cap_seconds) / Decimal(60) * entry.pricing.worst_case_usd_per_minute).quantize(
        Decimal("0.000001")
    )


def budget_refuses(*, headroom: Decimal | None, worst: Decimal) -> bool:
    """Whether the remaining budget cannot cover the worst case (spec §2.4)."""
    return headroom is not None and headroom < worst
