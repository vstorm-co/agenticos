"""Who may record, checked again at every transition and before every accepted event.

The answer is always read fresh: current membership and role, the run's state,
and access to the agent. A person removed from the organization, a run that
ended, or an agent whose run permission was withdrawn stops capture at the next
event rather than at the next start.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator
from app.core.browser_teaching import TeachingReason, TeachingRefused
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.repositories import agent as agent_repo
from app.repositories import agent_run as run_repo
from app.services.access import AGENT, member_context, resolve_access


def deployment_enabled(organization_id: UUID) -> bool:
    """The deployment flag, narrowed to the organizations it names. Off by default."""
    return (
        settings.BROWSER_TEACHING_ENABLED
        and organization_id in settings.BROWSER_TEACHING_ORGANIZATION_IDS
    )


def require_enabled(organization_id: UUID) -> None:
    if not deployment_enabled(organization_id):
        raise TeachingRefused(TeachingReason.DISABLED)


def human_subject(ctx: AuthContext) -> UUID:
    """The signed-in person behind a request; API keys and impersonation are refused."""
    user_id = ctx.personal_user_id
    if user_id is None or ctx.api_key_id is not None or current_impersonator() is not None:
        raise TeachingRefused(TeachingReason.UNAVAILABLE)
    return user_id


def _personal(run: AgentRun | None, user_id: UUID) -> bool:
    """Whether the run is this person's own web run, not a delegated, keyed, triggered or system one."""
    return not (
        run is None
        or run.user_id != user_id
        or run.surface != RunSurface.WEB.value
        or run.parent_run_id is not None
        or run.key_scopes is not None
        or run.trigger_id is not None
        or run.system_role is not None
        or run.initiated_by_publisher_fallback
    )


async def _may_run_agent(db: AsyncSession, member: AuthContext, organization_id: UUID, agent_id: UUID) -> bool:
    agent = await agent_repo.get(db, agent_id, organization_id=organization_id)
    return (
        agent is not None
        and agent.status != "archived"
        and await resolve_access(db, member, agent, Perm.AGENTS_RUN, resource_type=AGENT)
    )


async def authority(
    db: AsyncSession, organization_id: UUID, user_id: UUID, run_id: UUID
) -> AgentRun:
    """The run, if this person may record in it now; refuse otherwise.

    The run must be running, started by this person on the web surface, and not
    delegated, keyed, triggered or a system run. The person must still be an
    active member with `skills:edit`, and may still run the agent.
    """
    member = await member_context(db, organization_id=organization_id, user_id=user_id)
    if member is None or not member.has(Perm.SKILLS_EDIT):
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    run = await run_repo.get_run(db, run_id, organization_id=organization_id)
    if run is not None:
        await db.refresh(run)
    if run is None or run.status != RunStatus.RUNNING.value or not _personal(run, user_id):
        raise TeachingRefused(TeachingReason.UNAVAILABLE)
    if not await _may_run_agent(db, member, organization_id, run.agent_id):
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    return run


async def reviewer(
    db: AsyncSession, organization_id: UUID, user_id: UUID, run_id: UUID, agent_id: UUID
) -> AuthContext:
    """The owner as the member they are now, if they may still review and propose.

    Review happens after capture, so the run need not be running any more. It
    must still be this person's own web run of the same agent, and they must
    still be an active member with `skills:edit` who may run that agent. Read
    fresh on every call: a queued proposal job asks again before it writes.
    """
    member = await member_context(db, organization_id=organization_id, user_id=user_id)
    if member is None or not member.has(Perm.SKILLS_EDIT):
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    run = await run_repo.get_run(db, run_id, organization_id=organization_id)
    if run is not None:
        await db.refresh(run)
    if run is None or run.agent_id != agent_id or not _personal(run, user_id):
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    if not await _may_run_agent(db, member, organization_id, agent_id):
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    return member
