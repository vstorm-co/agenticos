"""One deadline for a read that spans many statements, kept by the database itself.

A page reads several views, each in several statements, and has to answer within
a few seconds whatever any one of them costs. Nothing here cancels a query from
Python (`asyncio.timeout` around database I/O leaves a connection mid-protocol);
instead each statement is given its own `statement_timeout` just before it runs,
the smaller of a per-query limit and the time the page has left, so Postgres
stops it. `set_config(..., true)` lasts until the transaction ends, which is why
every statement is armed again rather than once: a statement left unarmed would
run under whatever limit was armed last, possibly seconds earlier.
"""

import math
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import virtual_table_repo
from app.services.virtual_tables.exceptions import DeadlineReached


class ReadDeadline:
    """A deadline `seconds` from now, armed on a session before each statement.

    Example:
        ```python
        deadline = ReadDeadline(5, 2_000)
        await deadline.arm(db)  # statement_timeout = min(2000 ms, time left)
        rows = await virtual_table_repo.list_record_sizes(db, ...)
        ```
    """

    def __init__(self, seconds: float, per_query_ms: int) -> None:
        self._ends = monotonic() + seconds
        self._per_query_ms = per_query_ms

    def remaining_ms(self) -> int:
        """Whole milliseconds left, rounded down; negative once the deadline has passed."""
        return math.floor((self._ends - monotonic()) * 1000)

    async def arm(self, db: AsyncSession) -> None:
        """Limit the next statement on `db` to the per-query limit or the time left.

        The clock is read once: a second reading could pass the check and then set
        `0`, which Postgres reads as no limit at all.

        Raises:
            DeadlineReached: Under a millisecond is left. Nothing is executed.
        """
        ms = min(self._per_query_ms, self.remaining_ms())
        if ms < 1:
            raise DeadlineReached(remaining_ms=ms)
        await virtual_table_repo.set_statement_timeout(db, ms=ms)


async def arm_if_set(db: AsyncSession, deadline: ReadDeadline | None) -> None:
    """Arm `deadline` on `db` when there is one: for a read some callers make without one.

    Raises:
        DeadlineReached: As `ReadDeadline.arm`.
    """
    if deadline is not None:
        await deadline.arm(db)
