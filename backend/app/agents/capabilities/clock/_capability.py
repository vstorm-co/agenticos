"""Telling an agent what time it is."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT

# Date, time, offset and zone name, in an unambiguous order. ISO-8601 rather
# than prose because a model asked to compute "14 days from now" does
# noticeably better arithmetic on 2026-07-27 than on "27 July 2026".
_FORMAT = "%Y-%m-%d %H:%M:%S %z (%Z)"


@dataclass
class Clock(AbstractCapability[AgentDepsT]):
    """Puts the current time in the agent's instructions.

    This was a tool, and a tool is the wrong shape for it. The current time is
    not something an agent should have to *decide* to look up — it is context,
    and a model that has to choose to ask usually does not: it answers from
    whatever date its training left it with, confidently and wrongly. A tool
    call also spends a whole extra round trip retrieving one line the server
    already knew before the run started.

    So it goes in the instructions, resolved per request rather than once at
    build time. A conversation open for an hour would otherwise keep repeating
    the minute it started with, which is the same bug wearing a smaller hat.

    Timezone is configuration because "today" is not a UTC question. For a team
    in Warsaw a run at 00:30 CEST is still the previous day in UTC, and an
    agent quietly reporting yesterday's date is wrong in a way nobody catches
    until it schedules something.
    """

    timezone: str = "UTC"
    """IANA zone the agent should think in, for example ``Europe/Warsaw``."""

    _zone: ZoneInfo = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Resolved here rather than per request, so a bad zone fails while
        # somebody is looking at the Builder instead of mid-run in front of a
        # user. Configuration arrives from JSON, so the annotation guarantees
        # nothing on its own.
        try:
            self._zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone: {self.timezone!r}") from exc

    def now(self) -> datetime:
        """The current time in the configured zone."""
        return datetime.now(UTC).astimezone(self._zone)

    def get_instructions(self) -> Callable[[RunContext[AgentDepsT]], str]:
        """A callable, not a string — so each request gets the time it ran at."""
        return self._line

    def _line(self, _ctx: RunContext[AgentDepsT]) -> str:
        return f"The current date and time is {self.now().strftime(_FORMAT)}."
