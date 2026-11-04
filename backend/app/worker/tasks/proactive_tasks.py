"""The platform's own initiative, run by the worker (#2301).

Each job opens its own session, does one person's work and commits. Nothing here
runs inside somebody's request: a request only queues the job.
"""

import logging

from app.db.session import get_db_context
from app.services.proactive import ProactiveService
from app.worker.jobs import (
    InstallRolePack,
    LookThroughWatch,
    ThinkForPerson,
    Tick,
    WelcomeMember,
)

logger = logging.getLogger(__name__)


async def proactive_sweep(tick: Tick) -> int:
    """Queue the nightly look for whoever's morning it is. Returns how many were queued."""
    async with get_db_context() as db:
        queued = await ProactiveService(db).sweep(now=tick.scheduled_for)
    if queued:
        logger.info("Proactive sweep: %d person(s) queued", queued)
    return queued


async def think_for_person(payload: ThinkForPerson) -> int:
    async with get_db_context() as db:
        return await ProactiveService(db).think_for(payload.organization_id, payload.user_id)


async def watch_sweep(tick: Tick) -> int:
    """Queue a look for each watch whose time has come. Returns how many were queued."""
    async with get_db_context() as db:
        return await ProactiveService(db).sweep_watches(now=tick.scheduled_for)


async def look_through_watch(payload: LookThroughWatch) -> int:
    async with get_db_context() as db:
        return await ProactiveService(db).look_through(payload.watch_id)


async def brief_person(payload: ThinkForPerson) -> int:
    async with get_db_context() as db:
        return await ProactiveService(db).brief(payload.organization_id, payload.user_id)


async def install_role_pack(payload: InstallRolePack) -> int:
    async with get_db_context() as db:
        return await ProactiveService(db).install_role_pack(
            payload.organization_id, payload.user_id, payload.pack_id
        )


async def welcome_member(payload: WelcomeMember) -> int:
    async with get_db_context() as db:
        return await ProactiveService(db).welcome(payload.organization_id, payload.user_id)
