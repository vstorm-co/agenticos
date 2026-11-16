"""Current human, private run and published capability authority at every transition."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.audit import current_impersonator
from app.core.browser_teaching import TeachingReason, TeachingRefused
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.browser_teaching import BrowserTeachingPolicy, BrowserTeachingSession
from app.db.models.skill import Skill
from app.repositories import agent as agent_repo
from app.repositories import agent_run as run_repo
from app.repositories import browser_credential as private_repo
from app.repositories import browser_teaching as repo
from app.repositories import skill as skill_repo
from app.services.access import AGENT, SKILL, member_context, resolve_access

from ._lease import TeachingIdentity, TeachingRunIdentity


def deployment_enabled(organization_id: UUID) -> bool:
    return (
        settings.BROWSER_TEACHING_ENABLED
        and organization_id in settings.BROWSER_TEACHING_ORGANIZATION_IDS
    )


async def person(db: AsyncSession, ctx: AuthContext) -> AuthContext:
    user_id = ctx.personal_user_id
    if user_id is None or ctx.api_key_id is not None or current_impersonator() is not None:
        raise TeachingRefused(TeachingReason.UNAVAILABLE)
    current = await member_context(db, organization_id=ctx.organization_id, user_id=user_id)
    if current is None:
        raise TeachingRefused(TeachingReason.UNAVAILABLE)
    return current


async def enabled(db: AsyncSession, organization_id: UUID) -> BrowserTeachingPolicy:
    policy = await repo.policy(db, organization_id)
    if not deployment_enabled(organization_id) or policy is None or not policy.enabled:
        raise TeachingRefused(TeachingReason.DISABLED)
    return policy


def _configuration(raw: object) -> tuple[bool, bool]:
    # Lazy import keeps registry construction free of a capability/service cycle.
    from app.agents.capabilities.browser_use import WebBrowserConfig

    try:
        spec = AgentSpec.model_validate(raw)
        binding = next(
            item for item in spec.capabilities if item.id == "browser_use" and item.enabled
        )
        config = WebBrowserConfig.model_validate(binding.config)
    except ValidationError, StopIteration:
        raise TeachingRefused(TeachingReason.UNAVAILABLE) from None
    if (
        config.connection != "built_in"
        or not settings.BROWSER_SIGN_IN_CDP_URL
        or config.cdp_url.rstrip("/") != settings.BROWSER_SIGN_IN_CDP_URL.rstrip("/")
    ):
        raise TeachingRefused(TeachingReason.UNAVAILABLE)
    return config.allow_teaching, config.learn_site_procedures


async def specifications(
    db: AsyncSession, run: AgentRun, agent: Agent
) -> tuple[AgentSpec, AgentSpec]:
    frozen = run.test_spec
    if frozen is None and run.agent_version_id is not None:
        version = await agent_repo.get_version(
            db, run.agent_version_id, organization_id=run.organization_id
        )
        if version is not None and version.agent_id == run.agent_id:
            frozen = version.spec
    current = agent.draft_spec if run.test_spec is not None else None
    if run.test_spec is None and agent.current_version_id is not None:
        version = await agent_repo.get_version(
            db, agent.current_version_id, organization_id=run.organization_id
        )
        if version is not None and version.agent_id == run.agent_id:
            current = version.spec
    try:
        return AgentSpec.model_validate(frozen), AgentSpec.model_validate(current)
    except ValidationError:
        raise TeachingRefused(TeachingReason.UNAVAILABLE) from None


async def _configurations(db: AsyncSession, run: AgentRun, agent: Agent) -> tuple[bool, bool]:
    frozen, current = await specifications(db, run, agent)
    old_capture, old_learning = _configuration(frozen)
    new_capture, new_learning = _configuration(current)
    return old_capture and new_capture, old_learning and new_learning


@dataclass(frozen=True)
class Admission:
    context: AuthContext
    run: AgentRun
    policy: BrowserTeachingPolicy
    learning_allowed: bool


async def current_run(
    db: AsyncSession, ctx: AuthContext, identity: TeachingRunIdentity, *, live: bool
) -> tuple[AuthContext, AgentRun, Agent]:
    current = await person(db, ctx)
    if current.user_id != identity.user_id or current.organization_id != identity.organization_id:
        raise TeachingRefused(TeachingReason.UNAVAILABLE)
    run = await run_repo.get_run(db, identity.run_id, organization_id=identity.organization_id)
    if run is not None:
        await db.refresh(run)
    if (
        run is None
        or (live and run.status != RunStatus.RUNNING.value)
        or run.user_id != identity.user_id
        or run.agent_id != identity.agent_id
        or run.surface != RunSurface.WEB.value
        or run.initiated_by_publisher_fallback
        or run.key_scopes is not None
        or run.parent_run_id is not None
        or run.trigger_id is not None
        or run.routine_origin_id is not None
        or run.system_role is not None
        or run.conversation_id is None
        or not await private_repo.private_conversation(
            db, identity.organization_id, run.conversation_id, identity.user_id
        )
    ):
        raise TeachingRefused(TeachingReason.UNAVAILABLE)
    agent = await agent_repo.get(db, run.agent_id, organization_id=identity.organization_id)
    if agent is not None:
        await db.refresh(agent)
    if (
        agent is None
        or agent.status == "archived"
        or not await resolve_access(db, current, agent, Perm.AGENTS_RUN, resource_type=AGENT)
    ):
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    return current, run, agent


async def admit(
    db: AsyncSession, ctx: AuthContext, identity: TeachingIdentity, *, live: bool
) -> Admission:
    current, run, agent = await current_run(db, ctx, identity, live=live)
    policy = await enabled(db, current.organization_id)
    capture, learning = await _configurations(db, run, agent)
    if not capture:
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    return Admission(current, run, policy, learning)


async def target(db: AsyncSession, ctx: AuthContext, skill_id: UUID | None) -> Skill | None:
    if skill_id is None:
        if not ctx.has(Perm.SKILLS_EDIT):
            raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
        return None
    skill = await skill_repo.get(db, skill_id, organization_id=ctx.organization_id)
    if skill is not None:
        await db.refresh(skill)
    if skill is None or not await resolve_access(
        db, ctx, skill, Perm.SKILLS_EDIT, resource_type=SKILL
    ):
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    return skill


def identity_of(row: BrowserTeachingSession) -> TeachingIdentity:
    return TeachingIdentity(
        organization_id=row.organization_id,
        run_id=row.run_id,
        agent_id=row.agent_id,
        user_id=row.owner_user_id,
        controller_id=row.controller_id,
        tab_id=row.tab_id,
        call_id=row.call_id,
    )


async def authorize(
    db: AsyncSession, ctx: AuthContext, row: BrowserTeachingSession, *, live: bool
) -> Admission:
    admission = await admit(db, ctx, identity_of(row), live=live)
    if admission.policy.generation != row.policy_generation:
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    await target(db, admission.context, row.target_skill_id)
    if row.source == "refinement":
        preference = await repo.preference(db, row.organization_id, row.owner_user_id, row.agent_id)
        if (
            admission.run.test_spec is not None
            or not admission.learning_allowed
            or preference is None
            or not preference.enabled
            or preference.generation != row.preference_generation
        ):
            raise TeachingRefused(TeachingReason.OPTED_OUT)
    return admission


def require_reviewable(row: BrowserTeachingSession, run: AgentRun) -> None:
    if row.source == "refinement" and (
        not row.browser_completed
        or not row.verified_success
        or run.status != RunStatus.COMPLETED.value
    ):
        raise TeachingRefused(TeachingReason.TASK_NOT_COMPLETED)
