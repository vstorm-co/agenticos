"""`ProactiveService`: everything the platform does for people on its own initiative (#2301).

All of it happens in background jobs, never inside somebody's request: the
nightly look at each person's week, installing a role pack they accepted, and
greeting a new member in the chat apps. A request only ever queues one of these.
"""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import member_repo
from app.repositories.member import SweepCandidate
from app.schemas.user import WorkingHours
from app.services.background_jobs import enqueue
from app.worker.jobs import (
    INSTALL_ROLE_PACK,
    THINK_FOR_PERSON,
    WELCOME_MEMBER,
    InstallRolePack,
    ThinkForPerson,
    WelcomeMember,
)

# The starter agent's handle - `_thinker.STARTER_SLUG`, repeated here so queueing
# stays light (below).
_STARTER_SLUG = "agenticos"

# From the hour the organization chose, three hours wide: the sweep is hourly,
# and one that misses a tick still lands. `NightlyLook.due` keeps it to once.
_WINDOW_HOURS = 3


def _its_time(candidate: SweepCandidate, now: datetime) -> bool:
    """Whether it is this person's hour, on one of the organization's days, where they are.

    `before_work` aims an hour before the working hours their profile states and
    falls back to the organization's hour for a profile that states none.
    """
    local = now.astimezone(ZoneInfo(candidate.time_zone or "UTC"))
    if local.isoweekday() not in candidate.days:
        return False
    hour = candidate.hour
    if candidate.timing == "before_work" and candidate.working_hours is not None:
        hour = (WorkingHours.model_validate(candidate.working_hours).start_hour - 1) % 24
    return (local.hour - hour) % 24 < _WINDOW_HOURS


class ProactiveService:
    """Queueing is light; the work is deferred.

    The services that add a member - invitations, the default organization,
    directory sync - queue a welcome from here, and they sit underneath the agent
    runtime that the work itself needs (routines, the model call). So the methods
    that run in the worker import their modules when called, and importing this
    class costs a queueing service nothing.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def sweep(self, *, now: datetime) -> int:
        """Queue the nightly look for everybody whose hour it is and who is due.

        Returns how many were queued. The look itself decides whether there is
        anything to read; this only decides whose turn it is.
        """
        from app.services.proactive._nightly import NightlyLook

        nightly = NightlyLook(self.db)
        queued = 0
        for candidate in await member_repo.sweep_candidates(self.db, agent_slug=_STARTER_SLUG):
            if not _its_time(candidate, now):
                continue
            if not await nightly.due(candidate.organization_id, candidate.user_id, now=now):
                continue
            await enqueue(
                self.db,
                THINK_FOR_PERSON,
                ThinkForPerson(
                    organization_id=candidate.organization_id, user_id=candidate.user_id
                ),
                organization_id=candidate.organization_id,
            )
            queued += 1
        return queued

    async def think_for(self, organization_id: UUID, user_id: UUID) -> int:
        """The nightly look at one person. Returns how many proposals are new."""
        from app.services.proactive._nightly import NightlyLook

        return await NightlyLook(self.db).look(organization_id, user_id)

    async def queue_role_pack(self, organization_id: UUID, user_id: UUID, pack_id: str) -> None:
        """Install a role pack the person accepted, in the background."""
        await enqueue(
            self.db,
            INSTALL_ROLE_PACK,
            InstallRolePack(organization_id=organization_id, user_id=user_id, pack_id=pack_id),
            organization_id=organization_id,
        )

    async def install_role_pack(self, organization_id: UUID, user_id: UUID, pack_id: str) -> int:
        from app.services.proactive import _role_pack

        return await _role_pack.install(self.db, organization_id, user_id, pack_id)

    async def queue_welcome(self, organization_id: UUID, user_id: UUID) -> None:
        """Greet somebody who just joined, in the background, in the request that added them."""
        await enqueue(
            self.db,
            WELCOME_MEMBER,
            WelcomeMember(organization_id=organization_id, user_id=user_id),
            organization_id=organization_id,
        )

    async def welcome(self, organization_id: UUID, user_id: UUID) -> int:
        from app.services.proactive import _welcome

        return await _welcome.welcome(self.db, organization_id, user_id)
