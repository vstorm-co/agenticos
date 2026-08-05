"""Find published agents that lend a skill their publisher could not reach.

This is the residual of #179. That change added a publish-time check: binding a
skill hands its body and its files to every run of the agent, so the publisher
has to be able to read it themselves (`AgentRegistryService._skill_problems`).
Validation on this platform runs at publish and never at run time, deliberately -
`SkillService.resolve_for_agent` resolves a frozen spec's `skill_ids` with the
tenant filter only, because a runner-scoped check would refuse every subject-less
context, which is every API key, embedded widget and channel message.

So the check protects every *future* publish and nothing already frozen. A
version published before it keeps handing out whatever its `skill_ids` named -
including another member's private skill - on every run, and the only signal
anybody gets is that the *next* publish of that agent is refused. This sweep is
the offline half: it names those versions so an operator can decide what to do.

It scans every version a run can load, not only `current_version_id`: a named
environment can stay pinned to an older version while the default moves on, and
a parent can pin a delegate version by id - both execute, so both are checked.
See :func:`_executable_versions`.
It is report-only on purpose. A spec is what a client exports into their own git
repository, so silently unbinding a skill would rewrite something outside this
deployment; the decision stays with a person.

**The answer is about the row, not about today's membership**, and that is the
whole subtlety. Re-deriving "can the publisher reach this skill *now*" would move
with the publisher's role: an author promoted after a bad publish would look
innocent, and one demoted after a good one would look guilty - the same
time-dependence that makes a run-time re-check wrong. So reachability here is
evaluated at the floor every skill-viewing role shares (`Scope.SHARED`): a
binding is fine only if the skill is org-visible, owned by the publisher, or
explicitly granted to them - all facts of the rows, invariant to whatever role
the publisher holds today. A publisher whose user row is gone
(`published_by_user_id` is nullable, `ON DELETE SET NULL`) is reported as
*unknown* rather than guessed either way.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.spec import AgentSpec
from app.commands import command, error, info, success, warning
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.db.session import get_db_context
from app.repositories import agent_repo, member_repo, resource_grant_repo, skill_repo
from app.services.access import SKILL
from app.services.agent_registry import delegation_binding


class BindingStatus(StrEnum):
    """What a sweep can conclude about one frozen skill binding.

    Only the two that need reporting exist - a reachable binding produces no
    finding at all, so there is no `OK` member to filter back out.
    """

    EXPOSED = "exposed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SkillBinding:
    """One skill named by one running spec, and where in it.

    `specialist` is `None` for the agent's own `skill_ids` and the specialist's
    name for one bound inside an inline specialist - the second place a
    `skill_id` hides, and the half of #179 easy to forget.
    """

    skill_id: UUID
    specialist: str | None


@dataclass(frozen=True)
class Finding:
    """One binding a running spec should not be handing out, and who to ask."""

    organization_id: UUID
    agent_slug: str
    agent_name: str
    version_number: int
    published_by_user_id: UUID | None
    publisher_email: str | None
    skill_id: UUID
    skill_name: str
    specialist: str | None
    status: BindingStatus


def _bindings(spec: AgentSpec) -> list[SkillBinding]:
    """Every skill this spec binds - its own, and each inline specialist's.

    A delegating agent carries specialists inside its delegation capability, and
    each specialist has its own `skill_ids` that publish validates through the
    same `_skill_problems`. A config that does not parse as `SubagentsConfig` is
    skipped rather than guessed at: the capability would not build from it, so
    those specialists never run and can lend nothing - the same reason
    `_delegate_problems` stops there.
    """
    bindings = [SkillBinding(skill_id=skill_id, specialist=None) for skill_id in spec.skill_ids]
    binding = delegation_binding(spec)
    if binding is not None:
        try:
            config = SubagentsConfig.model_validate(binding.config)
        except ValidationError:
            return bindings
        for specialist in config.inline:
            bindings.extend(
                SkillBinding(skill_id=skill_id, specialist=specialist.name)
                for skill_id in specialist.skill_ids
            )
    return bindings


async def _classify(
    db: AsyncSession,
    *,
    organization_id: UUID,
    publisher_id: UUID | None,
    skill: Skill,
) -> BindingStatus | None:
    """Whether this binding is a problem, and which kind - or `None` if it is fine.

    The same question publish asks through :func:`resolve_access`, pinned to the
    `Scope.SHARED` floor so the answer is a fact about the rows and not about the
    publisher's role today: org-visible, owned by the publisher, or granted to
    them. SHARED is the least any role that can view skills at all is given, so
    "not reachable at the floor" means the binding depended on the publisher's
    role being higher than that - which is exactly the exposure, and exactly what
    must not silently un-flag itself when that role later changes.
    """
    # Org-visible skills are readable by every member, so who published the spec
    # never mattered - and still does not, even if that publisher has since left.
    if skill.visibility == Visibility.ORG.value:
        return None
    # The publisher's user row is gone. Ownership and grants both key on a person
    # and there is none, so this cannot be decided rather than guessed. A private
    # skill with no knowable publisher is the oldest, least visible case, so it is
    # surfaced as unknown, not silently cleared.
    if publisher_id is None:
        return BindingStatus.UNKNOWN
    if skill.owner_user_id == publisher_id:
        return None
    # Any grant is enough. The lowest level, `READ`, already sees the skill's
    # body, which is what a bound skill hands a run - so `resolve_access` treats
    # any grant as sufficient for `SKILLS_VIEW`, and a level comparison here would
    # be a tautology dressed as a check.
    level = await resource_grant_repo.get_level(
        db,
        organization_id=organization_id,
        subject_user_id=publisher_id,
        resource_type=SKILL.key,
        resource_id=skill.id,
    )
    if level is not None:
        return None
    return BindingStatus.EXPOSED


async def _findings_for(db: AsyncSession, agent: Agent, version: AgentVersion) -> list[Finding]:
    """Every problematic binding in one running spec.

    Only a skill that would actually load is judged, which is exactly what
    `resolve_for_agent` loads: present, this organization's, and enabled. A
    skill_id the org-scoped fetch does not return is deleted or another tenant's,
    and a disabled one is skipped by `resolve_for_agent` too - both hand nothing
    to a run, so both are dangling references left to that path rather than
    reported as an exposure that would fail the audit.
    """
    spec = AgentSpec.model_validate(version.spec)
    bindings = _bindings(spec)
    if not bindings:
        return []

    skills = await skill_repo.get_many(
        db, [binding.skill_id for binding in bindings], organization_id=agent.organization_id
    )
    findings: list[Finding] = []
    for binding in bindings:
        skill = skills.get(binding.skill_id)
        if skill is None or not skill.enabled:
            continue
        status = await _classify(
            db,
            organization_id=agent.organization_id,
            publisher_id=version.published_by_user_id,
            skill=skill,
        )
        if status is None:
            continue
        findings.append(
            Finding(
                organization_id=agent.organization_id,
                agent_slug=agent.slug,
                agent_name=agent.name,
                version_number=version.version,
                published_by_user_id=version.published_by_user_id,
                publisher_email=None,
                skill_id=skill.id,
                skill_name=skill.name,
                specialist=binding.specialist,
                status=status,
            )
        )
    return await _with_publisher_email(db, agent, version, findings)


async def _with_publisher_email(
    db: AsyncSession, agent: Agent, version: AgentVersion, findings: list[Finding]
) -> list[Finding]:
    """Fill in the publisher's email, once, for a version that has any findings.

    Restricted to the organization's members, so a publisher who has left the org
    - user row still present, membership gone - resolves to no email and is shown
    by id. That absence is information: it is a different state from a deleted
    user, and the report should not blur the two.
    """
    if not findings or version.published_by_user_id is None:
        return findings
    emails = await member_repo.get_emails_for_users(
        db, organization_id=agent.organization_id, user_ids=[version.published_by_user_id]
    )
    email = emails.get(version.published_by_user_id)
    if email is None:
        return findings
    return [replace(finding, publisher_email=email) for finding in findings]


async def _executable_versions(db: AsyncSession) -> list[tuple[Agent, AgentVersion]]:
    """Every version a run can load, each with its agent, deduplicated.

    Three ways a frozen version reaches a run, and only the first is
    `current_version_id`:

    - the default environment, which is `current_version_id`;
    - any named environment, which can stay pinned to an older version while the
      default moves on;
    - a `SubagentRef` in an executing spec, which pins a delegate version by id
      and is followed by the caller - transitively, since that delegate's own
      spec can pin further.

    A sweep that looked only at the current version would report a production
    environment pinned to an unsafe v1 as clean, and miss a parent still
    delegating to a delegate's unsafe pinned version. So the environments seed the
    set and the pins close it, id by id, until nothing new is reached.

    A delegate whose agent has since been archived is dropped, because the runner
    refuses to delegate to an archived agent (`_resolve_delegate` in
    `agent_runner.py`): its pinned version can no longer load through that pin, so
    reporting it would be flagging a binding no run can reach. The seeds cannot be
    archived - both queries filter to published agents - so the check is only ever
    needed on the delegates the closure reaches.
    """
    seen: dict[UUID, tuple[Agent, AgentVersion]] = {}
    frontier: list[AgentVersion] = []
    seeds = [
        *await agent_repo.list_current_versions(db),
        *await agent_repo.list_environment_versions(db),
    ]
    for agent, version in seeds:
        if version.id not in seen:
            seen[version.id] = (agent, version)
            frontier.append(version)

    while frontier:
        version = frontier.pop()
        spec = AgentSpec.model_validate(version.spec)
        pin_ids = [ref.agent_version_id for ref in spec.subagents]
        for agent, pinned in await agent_repo.get_versions_with_agents(db, pin_ids):
            if agent.status == AgentStatus.ARCHIVED.value:
                continue
            # A cycle (A pins B, B pins A) or two parents pinning one delegate
            # reach the same version twice; the first sighting wins and the rest
            # are skipped here, which is what makes the closure terminate.
            if pinned.id not in seen:
                seen[pinned.id] = (agent, pinned)
                frontier.append(pinned)

    return list(seen.values())


async def _scan(db: AsyncSession) -> list[Finding]:
    """Every problematic binding across every version a run can load."""
    findings: list[Finding] = []
    for agent, version in await _executable_versions(db):
        findings.extend(await _findings_for(db, agent, version))
    return findings


def _publisher(finding: Finding) -> str:
    """How to name the publisher in a report line."""
    if finding.published_by_user_id is None:
        return "unknown (the publisher's user was deleted)"
    return finding.publisher_email or f"{finding.published_by_user_id} (not a current member)"


def _location(finding: Finding) -> str:
    """Where in the spec the binding sits."""
    if finding.specialist is None:
        return "agent skill_ids"
    return f"specialist '{finding.specialist}'"


def _line(finding: Finding) -> str:
    return (
        f"  {finding.agent_slug} v{finding.version_number} "
        f"(org {finding.organization_id}) - skill '{finding.skill_name}' ({finding.skill_id}) "
        f"in {_location(finding)}, published by {_publisher(finding)}"
    )


def _report(findings: list[Finding]) -> int:
    """Print the findings grouped by kind. Returns the number that are exposures."""
    exposed = [finding for finding in findings if finding.status is BindingStatus.EXPOSED]
    unknown = [finding for finding in findings if finding.status is BindingStatus.UNKNOWN]

    if not findings:
        success("No published agent lends a skill its publisher could not reach.")
        return 0

    if exposed:
        error(f"{len(exposed)} binding(s) lend a skill the publisher could not reach:")
        for finding in exposed:
            error(_line(finding))
    if unknown:
        warning(
            f"{len(unknown)} binding(s) name a private skill whose publisher is gone - "
            "reachability cannot be decided:"
        )
        for finding in unknown:
            warning(_line(finding))

    info(
        "\nNothing was changed. A binding is exported into the agent's spec, so unbinding "
        "one is a decision for a person: re-publishing the agent re-runs the check and "
        "refuses it, or the skill can be shared with the publisher to make the binding legitimate."
    )
    return len(exposed)


async def _run() -> int:
    async with get_db_context() as db:
        findings = await _scan(db)
    return _report(findings)


@command(
    "audit-skill-bindings",
    help="Find published agents that lend a skill their publisher could not reach",
)
def audit_skill_bindings() -> None:
    """Report frozen skill bindings a publish-time check would refuse today.

    Read-only. Exits non-zero when it finds a binding that lends a skill the
    publisher could not reach, so it can gate a cron or a provisioning script; a
    binding whose publisher has left is a warning, not a failure, because there is
    nobody left to check it against.

    Example:
        agenticos cmd audit-skill-bindings
    """
    info(
        "Auditing every runnable version of every published agent for out-of-reach skill bindings..."
    )
    exposed = asyncio.run(_run())
    if exposed:
        raise SystemExit(1)
