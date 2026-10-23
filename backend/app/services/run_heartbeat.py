"""A running run's sign of life, so a dead process's runs end in minutes.

A run's row is committed `running` before its model is called, and only the
process executing it ever finishes it. When that process dies - a deploy, an
OOM, a restart mid-turn - nothing says so, and the stale-run sweep used to wait
six hours before ending the row, while the chat said "Working" over a turn
nothing was answering. While its model works the executing process stamps the
row every few seconds, so the sweep can end a run that went quiet after a
couple of minutes (`RunReaperService`).

Each run beats for itself, from inside the process executing it, rather than
one loop per process over a registry: a worker executes jobs in child
processes, which a registry in the parent never sees.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID

from app.core.config import settings
from app.db.session import get_db_context
from app.repositories import agent_run_repo

logger = logging.getLogger(__name__)


async def _beat(run_id: UUID, every: float) -> None:
    while True:
        await asyncio.sleep(every)
        # A beat that fails is logged and the next one tried: the run itself is
        # fine, and ending it over a dropped connection would be the sweep's
        # mistake made early. Missing beats long enough is what the sweep is for.
        try:
            async with get_db_context() as db:
                await agent_run_repo.beat_run(db, run_id=run_id, at=datetime.now(UTC))
        except Exception:
            logger.exception("run_heartbeat_failed", extra={"run_id": str(run_id)})


@contextlib.asynccontextmanager
async def run_heartbeat(run_id: UUID) -> AsyncGenerator[None]:
    """Stamp `run_id` as alive every `RUN_HEARTBEAT_SECONDS` until the block ends.

    Its own session per beat, never the run's: the run holds no connection
    while its model works (#12), and a beat must not open a transaction on the
    session the run's terminal write commits.
    """
    beating = asyncio.create_task(
        _beat(run_id, settings.RUN_HEARTBEAT_SECONDS), name=f"run-heartbeat:{run_id}"
    )
    try:
        yield
    finally:
        beating.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beating
