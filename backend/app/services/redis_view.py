"""How the chat's live views fail when Redis does: briefly, and quietly.

Who is in a room (`chat_room`) and a turn still being written (`live_turn`) are
views: with Redis away the chat still works, only less live. So every call they
make is bounded by `TIMEOUT_SECONDS` - a Redis that stopped answering held a
socket's frame, or a turn's every token, until the kernel gave up on the
connection - and a failure is logged at most once per `LOG_EVERY_SECONDS` for each
kind of call. An outage used to log one traceback per open socket per retry, and
a few hundred open chats buried the line that said what had broken.
"""

import logging
import time

TIMEOUT_SECONDS = 2.0
"""How long one call may take before it counts as Redis being away."""

LOG_EVERY_SECONDS = 60.0
"""How often one kind of failure is logged while it keeps happening."""

_logged_at: dict[str, float] = {}
_unlogged: dict[str, int] = {}


def failed(logger: logging.Logger, event: str, error: Exception) -> None:
    """Log `error` as `event`, unless that event was logged lately.

    The entry it does log carries how many were left out since the last one, so
    the volume of an outage is still in the log, as one number.
    """
    now = time.monotonic()
    last = _logged_at.get(event)
    if last is not None and now - last < LOG_EVERY_SECONDS:
        _unlogged[event] = _unlogged.get(event, 0) + 1
        return
    _logged_at[event] = now
    logger.warning(event, exc_info=error, extra={"unlogged": _unlogged.pop(event, 0)})
