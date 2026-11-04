"""`ProactiveService`: everything the platform does for people on its own initiative (#2301).

All of it happens in background jobs, never inside somebody's request: the
nightly look at each person's week, installing a role pack they accepted, and
greeting a new member in the chat apps. A request only ever queues one of these.
"""

from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import member_repo
from app.repositories.member import SweepCandidate
from app.schemas.user import WorkingHours
from app.services.background_jobs import enqueue
from app.worker.jobs import (
    BRIEF_PERSON,
    INSTALL_ROLE_PACK,
    LOOK_THROUGH_WATCH,
    THINK_FOR_PERSON,
    WELCOME_MEMBER,
    InstallRolePack,
    LookThroughWatch,
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

    Anchored on the day's actual occurrence, date and all - today's, or
    yesterday's when a late hour's window runs past midnight - so the small
    hours of Monday are not read as the tail of Monday's 23:00 (Codex on #2324).
    """
    zone = ZoneInfo(candidate.time_zone or "UTC")
    local = now.astimezone(zone)
    hour = candidate.hour
    if candidate.timing == "before_work" and candidate.working_hours is not None:
        hour = (WorkingHours.model_validate(candidate.working_hours).start_hour - 1) % 24
    for days_back in (0, 1):
        day = local.date() - timedelta(days=days_back)
        if day.isoweekday() not in candidate.days:
            continue
        start = datetime.combine(day, time(hour), tzinfo=zone)
        if start <= local < start + timedelta(hours=_WINDOW_HOURS):
            return True
    return False


def _per_person(kind: str, organization_id: UUID, user_id: UUID) -> str:
    """The dedupe key of one person's job of `kind` in one organization."""
    return f"{kind}:{organization_id}:{user_id}"


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

        And the morning briefing, at the same hour, for whoever has findings
        waiting. Returns how many of both were queued. Each job decides whether
        there is anything to read or to say; this only decides whose turn it is.
        """
        from app.services.proactive._nightly import NightlyLook

        nightly = NightlyLook(self.db)
        queued = 0
        for candidate in await member_repo.sweep_candidates(self.db, agent_slug=_STARTER_SLUG):
            if not _its_time(candidate, now):
                continue
            if not await nightly.due(candidate.organization_id, candidate.user_id, now=now):
                continue
            # One look per person at a time: a look still queued behind a busy
            # pool at the next sweep would otherwise run twice, and both copies
            # would pass the same spend check.
            await enqueue(
                self.db,
                THINK_FOR_PERSON,
                ThinkForPerson(
                    organization_id=candidate.organization_id, user_id=candidate.user_id
                ),
                organization_id=candidate.organization_id,
                dedupe_key=_per_person("think", candidate.organization_id, candidate.user_id),
                dedupe_active=True,
            )
            queued += 1
        for candidate in await member_repo.briefing_candidates(self.db):
            if not _its_time(candidate, now):
                continue
            await enqueue(
                self.db,
                BRIEF_PERSON,
                ThinkForPerson(
                    organization_id=candidate.organization_id, user_id=candidate.user_id
                ),
                organization_id=candidate.organization_id,
                dedupe_key=_per_person("brief", candidate.organization_id, candidate.user_id),
                dedupe_active=True,
            )
            queued += 1
        return queued

    async def think_for(self, organization_id: UUID, user_id: UUID) -> int:
        """The nightly look at one person. Returns how many proposals are new."""
        from app.services.proactive._nightly import NightlyLook

        return await NightlyLook(self.db).look(organization_id, user_id)

    async def sweep_watches(self, *, now: datetime) -> int:
        """Queue a look for every watch whose time has come. Returns how many were queued."""
        from app.services.proactive._watch import WatchLook

        due = await WatchLook(self.db).due(now=now)
        for watch in due:
            await enqueue(
                self.db,
                LOOK_THROUGH_WATCH,
                LookThroughWatch(watch_id=watch.id),
                organization_id=watch.organization_id,
                dedupe_key=f"watch:{watch.id}",
                dedupe_active=True,
            )
        return len(due)

    async def look_through(self, watch_id: UUID) -> int:
        """One look through one watch's connection. Returns how many findings are new."""
        from app.services.proactive._watch import WatchLook

        return await WatchLook(self.db).look(watch_id)

    async def brief(self, organization_id: UUID, user_id: UUID) -> int:
        """One person's morning briefing. Returns how many findings it listed."""
        from app.services.proactive import _briefing

        return await _briefing.brief(self.db, organization_id, user_id, now=datetime.now(UTC))

    async def queue_role_pack(self, organization_id: UUID, user_id: UUID, pack_id: str) -> None:
        """Install a role pack the person accepted, in the background.

        One installation per person and pack at a time: two acceptances that both
        read the suggestion open - a double click - would each create the pack's
        routines.
        """
        await enqueue(
            self.db,
            INSTALL_ROLE_PACK,
            InstallRolePack(organization_id=organization_id, user_id=user_id, pack_id=pack_id),
            organization_id=organization_id,
            dedupe_key=f"{_per_person('role-pack', organization_id, user_id)}:{pack_id}",
            dedupe_active=True,
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
