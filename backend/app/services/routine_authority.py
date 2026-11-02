"""Current authorization for every tool of an unattended routine, including delegates.

The initial admission is still the trigger service's. This is its continuation:
pause, deletion, expiry, lost consent, role changes or revoked run grants take
effect before the next tool. A changed role requires a fresh run, so tool contexts
assembled under the previous role cannot retain its authority.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.session import get_db_context
from app.repositories import agent_repo, agent_trigger_repo, member_repo
from app.services.access import AGENT, resolve_access


def _refused() -> AuthorizationError:
    return AuthorizationError(
        message="This routine stopped or its authorization changed. Start a new run after reviewing its access."
    )


@dataclass(frozen=True)
class RoutineAuthority:
    routine_id: UUID
    organization_id: UUID
    user_id: UUID
    root_agent_id: UUID
    role: str
    acts_as_creator: bool

    @classmethod
    async def capture(
        cls,
        db: AsyncSession,
        ctx: AuthContext,
        *,
        agent_id: UUID,
        run: AgentRun | None,
    ) -> Self | None:
        """Freeze the actor's current role, retaining origin across approval and deletion."""
        origin = ctx.routine_id if run is None else run.routine_origin_id
        if origin is None:
            if run is not None and run.surface == RunSurface.SCHEDULE.value:
                raise _refused()
            return None
        person = ctx.user_id if run is None else run.user_id
        if person is None:
            raise _refused()
        member = await member_repo.get_active(
            db, organization_id=ctx.organization_id, user_id=person
        )
        if member is None or (run is None and member.role != ctx.role):
            raise _refused()
        authority = cls(
            routine_id=origin,
            organization_id=ctx.organization_id,
            user_id=person,
            root_agent_id=agent_id,
            role=member.role,
            acts_as_creator=(
                ctx.fired_as_creator is not None
                if run is None
                else not run.initiated_by_publisher_fallback
            ),
        )
        await authority.check_in(db, agent_id)
        return authority

    async def check(self, agent_id: UUID) -> None:
        """Use a short, fresh session; model calls never hold an authorization snapshot."""
        async with get_db_context() as db:
            await self.check_in(db, agent_id)

    async def check_in(self, db: AsyncSession, agent_id: UUID) -> None:
        trigger = await agent_trigger_repo.get(
            db, self.routine_id, organization_id=self.organization_id
        )
        if (
            trigger is None
            or not trigger.is_active
            or trigger.created_by_user_id != self.user_id
            or trigger.agent_id != self.root_agent_id
            or (trigger.ends_at is not None and trigger.ends_at <= datetime.now(UTC))
            or (self.acts_as_creator and not trigger.runs_as_creator)
        ):
            raise _refused()
        member = await member_repo.get_active(
            db, organization_id=self.organization_id, user_id=self.user_id
        )
        if member is None or member.role != self.role:
            raise _refused()
        current = AuthContext(
            user_id=self.user_id, organization_id=self.organization_id, role=member.role
        )
        for identifier in sorted({self.root_agent_id, agent_id}):
            agent = await agent_repo.get(db, identifier, organization_id=self.organization_id)
            if agent is None or agent.status == AgentStatus.ARCHIVED.value:
                raise _refused()
            # A published parent lends its pinned delegates, as _resolve_delegate
            # does. Requiring a new direct grant would change that contract.
            if identifier == self.root_agent_id and not await resolve_access(
                db, current, agent, Perm.AGENTS_RUN, resource_type=AGENT
            ):
                raise _refused()
