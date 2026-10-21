"""How long a call may run and whether it can be afforded (#54). Pure arithmetic."""

from decimal import Decimal

from app.services.realtime_models import RealtimeModelEntry

CALL_CEILING_SECONDS = 3000
"""50 minutes: below OpenAI's 60-minute hard stop, so our cap always lands first."""

DEFAULT_CALL_SECONDS = 600
"""10 minutes, for an agent whose Voice section names no longest call."""

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

ENDING_GRACE_SECONDS = 4.0
"""How long a start waits for a call its caller just hung up to finish ending before
counting the person as busy: "Call again" lands before the old call's teardown."""


def call_cap_seconds(*, agent_max: int | None, chain_elapsed: int) -> int:
    """The longest this connection may run: the agent's longest call, never negative.

    `chain_elapsed` is what earlier connections of the same call already used -
    a reconnect continues a call, it does not restart its clock.
    """
    cap = min(agent_max or DEFAULT_CALL_SECONDS, CALL_CEILING_SECONDS) - chain_elapsed
    return max(cap, 0)


def worst_case_usd(*, cap_seconds: int, entry: RealtimeModelEntry) -> Decimal:
    """What the call could cost at the model's worst price per minute, for the setup check."""
    return (Decimal(cap_seconds) / Decimal(60) * entry.pricing.worst_case_usd_per_minute).quantize(
        Decimal("0.000001")
    )


def budget_refuses(*, headroom: Decimal | None, worst: Decimal) -> bool:
    """Whether the remaining budget cannot cover the worst case (spec §2.4)."""
    return headroom is not None and headroom < worst
