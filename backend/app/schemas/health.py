"""System health schemas.

The status of a backing service, and what was done to find it out. ``detail`` is
not optional: a check that cannot say what it verified has no business
reporting a status, because "healthy" with nothing behind it is how a green
dashboard survives an outage.
"""

from datetime import datetime
from typing import Literal

from app.schemas.base import BaseSchema

CheckStatus = Literal["healthy", "unhealthy", "unconfigured", "not_checked"]
"""What a probe found.

``unhealthy`` is a thing that is broken. ``unconfigured`` is a thing this
deployment has not set up — not an incident, and not something to page anyone
about. ``not_checked`` is a probe that was skipped and says why, which is the
only honest answer when the check it depends on has already failed.
"""


class SystemCheck(BaseSchema):
    """One probe's outcome.

    ``key`` is stable and machine-readable; the label, icon and blurb belong to
    whatever renders it. ``latency_ms`` is present only when something was
    actually timed.
    """

    key: str
    status: CheckStatus
    detail: str
    latency_ms: float | None = None


class SystemHealthResponse(BaseSchema):
    """Every check this deployment can perform, for an authenticated operator."""

    checked_at: datetime
    checks: list[SystemCheck]
