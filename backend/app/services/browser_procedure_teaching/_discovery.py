"""Approved site procedures from this run's exact served skill versions."""

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills._log import SkillUseLog
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.browser_procedure_teaching import (
    MAX_EVENT_BYTES,
    BrowserProcedureTeachingProcedure,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.skill_proposal import ProposalStatus
from app.db.models.skill_version import SkillVersion, SkillVersionSource
from app.repositories import skill as skill_repo
from app.repositories import skill_proposal as proposal_repo
from app.repositories import skill_version as version_repo
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingDiscoveredProcedure
from app.services.access import SKILL, resolve_access

from . import _access
from ._lease import BrowserProcedureTeachingRunIdentity

MAX_CANDIDATES = 100
MAX_RESULTS = 20


def on_bound_line(spec: AgentSpec, version: SkillVersion) -> bool:
    if version.skill_id not in spec.skill_ids:
        return False
    binding = next(
        (item for item in spec.skill_bindings if item.skill_id == version.skill_id), None
    )
    if binding is None:
        return version.fork_id is None
    if binding.fork_id is not None:
        return binding.fork_id == version.fork_id
    return version.fork_id is None and binding.version == version.number


async def discover(
    db: AsyncSession, deps: AgentDeps, skill_log: SkillUseLog | None, origin: str
) -> tuple[BrowserProcedureTeachingDiscoveredProcedure, ...]:
    audience = deps.audience
    if (
        skill_log is None
        or not skill_log.own
        or skill_log.agent_id != deps.agent_id
        or deps.organization_id is None
        or deps.run_id is None
        or deps.agent_id is None
        or deps.impersonated
        or deps.delegated
        or audience is None
        or not audience.browses_signed_in
        or not audience.private
        or audience.user_id is None
        or audience.shared_transcript
        or deps.user_id != str(audience.user_id)
        or deps.run_person != audience.user_id
    ):
        raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.UNAVAILABLE)
    identity = BrowserProcedureTeachingRunIdentity(
        organization_id=deps.organization_id,
        run_id=deps.run_id,
        agent_id=deps.agent_id,
        user_id=audience.user_id,
    )
    ctx = AuthContext(
        user_id=identity.user_id, organization_id=identity.organization_id, role="member"
    )
    current, run, agent = await _access.current_run(db, ctx, identity, live=True)
    if run.test_spec is not None:
        raise BrowserProcedureTeachingRefused(BrowserProcedureTeachingReason.UNAVAILABLE)
    frozen, published = await _access.specifications(db, run, agent)
    # Creation may be disabled without deleting or hiding approved ordinary skills.
    # The browser capability and operator-managed endpoint must still be current.
    _access._configuration(frozen)
    _access._configuration(published)
    candidates = tuple(sorted(skill_log.served.items()))[:MAX_CANDIDATES]
    versions = await version_repo.get_versions(
        db,
        tuple(
            item.version_id
            for _, item in candidates
            if item.version_id is not None and not item.projected
        ),
        organization_id=current.organization_id,
    )
    results: list[BrowserProcedureTeachingDiscoveredProcedure] = []
    size = 0
    for name, served in candidates:
        if served.projected or served.version_id is None:
            continue
        version = versions.get(served.version_id)
        if (
            version is None
            or version.skill_id != served.skill_id
            or version.source != SkillVersionSource.BROWSER_TEACHING.value
            or version.proposal_id is None
            or version.browser_procedure is None
            or not on_bound_line(frozen, version)
            or not on_bound_line(published, version)
        ):
            continue
        skill = await skill_repo.get(db, served.skill_id, organization_id=current.organization_id)
        if skill is None:
            continue
        await db.refresh(skill)
        if not await resolve_access(db, current, skill, Perm.SKILLS_VIEW, resource_type=SKILL):
            continue
        proposal = await proposal_repo.get(
            db, version.proposal_id, organization_id=current.organization_id
        )
        if (
            proposal is None
            or proposal.status != ProposalStatus.APPLIED.value
            or proposal.source != SkillVersionSource.BROWSER_TEACHING.value
            or proposal.skill_id not in {None, version.skill_id}
            or proposal.browser_procedure != version.browser_procedure
            or proposal.content != version.content
            or proposal.description != version.description
        ):
            continue
        try:
            procedure = BrowserProcedureTeachingProcedure.model_validate(version.browser_procedure)
        except ValidationError:
            continue
        if origin not in procedure.origins:
            continue
        result = BrowserProcedureTeachingDiscoveredProcedure(
            skill_id=version.skill_id,
            skill_version_id=version.id,
            skill_name=name,
            procedure=procedure,
        )
        added = len(result.model_dump_json().encode())
        if size + added > MAX_EVENT_BYTES:
            continue
        results.append(result)
        size += added
        if len(results) == MAX_RESULTS:
            break
    return tuple(results)
