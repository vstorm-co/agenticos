"""Agent registry repositories (PostgreSQL async).

Listing an agent is not a plain org filter: what a member sees depends on their
role scope and on what was shared with them, so `list_visible` takes the
predicate pieces the access layer resolved rather than re-deriving them here.
"""

from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import Float, and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.resource_grant import Visibility


async def get_many(
    db: AsyncSession, agent_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, Agent]:
    """Several agents at once, by id, inside one organization.

    One statement rather than a lookup per row: the callers are listings that
    need a name beside each of a page of rows, and a query each is how a table of
    thirty becomes thirty round trips.
    """
    if not agent_ids:
        return {}
    result = await db.execute(
        select(Agent).where(Agent.id.in_(list(agent_ids)), Agent.organization_id == organization_id)
    )
    return {agent.id: agent for agent in result.scalars().all()}


async def existing_ids_locked(
    db: AsyncSession, agent_ids: Collection[UUID], *, organization_id: UUID
) -> set[UUID]:
    """Which of these agents still exist, locked so they cannot be deleted until commit.

    For the deferred approval write. A delegate whose gated call was parked can be
    deleted between the call and the run's terminal write - the write is deferred to
    that point - and its id rides on the approval row as a `SET NULL` foreign key.
    Inserting the row would then violate that key and roll the whole parked run
    back, so the writer nulls an id whose agent is gone. `FOR KEY SHARE` - the lock
    an insert referencing the row would itself take - holds the survivors so a
    concurrent delete cannot slip in between this check and that insert, which is
    the guarantee the old inline insert had and a bare existence check would lose.
    """
    if not agent_ids:
        return set()
    result = await db.execute(
        select(Agent.id)
        .where(Agent.id.in_(list(agent_ids)), Agent.organization_id == organization_id)
        .with_for_update(read=True, key_share=True)
    )
    return set(result.scalars().all())


async def get(db: AsyncSession, agent_id: UUID, *, organization_id: UUID) -> Agent | None:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_by_slug(db: AsyncSession, slug: str, *, organization_id: UUID) -> Agent | None:
    result = await db.execute(
        select(Agent).where(Agent.slug == slug, Agent.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    shared_with_me: bool = False,
    include_archived: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Agent], int]:
    """Agents this member may see, with a total count.

    Args:
        see_all: True when the role reaches the whole organization; the
            ownership predicate is then skipped entirely.
        shared_ids: Agent ids explicitly shared with this member.
        shared_with_me: Narrow to rows deliberately shared with the caller -
            org-visible or explicitly granted, and not their own. Applied
            whatever the role's scope: for a role that already sees
            everything, "shared with me" is still a question about grants
            and visibility, not reach.
    """
    query = select(Agent).where(Agent.organization_id == organization_id)
    count_query = select(func.count(Agent.id)).where(Agent.organization_id == organization_id)

    if not include_archived:
        query = query.where(Agent.status != AgentStatus.ARCHIVED.value)
        count_query = count_query.where(Agent.status != AgentStatus.ARCHIVED.value)

    if shared_with_me:
        shared = and_(
            or_(
                Agent.visibility == Visibility.ORG.value,
                Agent.id.in_(shared_ids) if shared_ids else false(),
            ),
            # IS DISTINCT FROM, not !=: an ownerless row is not the caller's.
            Agent.owner_user_id.is_distinct_from(user_id),
        )
        query = query.where(shared)
        count_query = count_query.where(shared)
    elif not see_all:
        visible = or_(
            Agent.owner_user_id == user_id,
            Agent.visibility == Visibility.ORG.value,
            Agent.id.in_(shared_ids) if shared_ids else False,
        )
        query = query.where(visible)
        count_query = count_query.where(visible)

    query = query.order_by(Agent.created_at.desc()).offset(skip).limit(limit)
    items = list((await db.execute(query)).scalars().all())
    total = (await db.execute(count_query)).scalar() or 0
    return items, total


async def published_budget_caps(
    db: AsyncSession, *, version_ids: Sequence[UUID]
) -> dict[UUID, float | None]:
    """Each version's monthly cap, read off the frozen spec's JSONB.

    One path extraction per row rather than loading whole specs: the listing
    needs one float from documents that can carry kilobytes of instructions.
    Keyed by version id - the caller joins them back onto its agents. A
    version whose spec has no budget block answers null, same as no cap.
    """
    if not version_ids:
        return {}
    cap = AgentVersion.spec["budget"]["monthly_usd"].astext.cast(Float)
    result = await db.execute(
        select(AgentVersion.id, cap).where(AgentVersion.id.in_(list(version_ids)))
    )
    return {row[0]: row[1] for row in result.all()}


async def published_model_profiles(
    db: AsyncSession, *, version_ids: Sequence[UUID]
) -> dict[UUID, UUID]:
    """Which model profile each version's frozen spec names, keyed by version id.

    The same one-path-per-row extraction `published_budget_caps` does, and for the
    same reason: the listing wants one id out of documents that can carry
    kilobytes of instructions.

    A version whose spec names no profile is absent rather than null - publish
    validation refuses a spec without one, so it can only be a spec that predates
    the rule, and there is nothing to resolve for it either way.
    """
    if not version_ids:
        return {}
    profile = AgentVersion.spec["model_profile_id"].astext
    result = await db.execute(
        select(AgentVersion.id, profile).where(AgentVersion.id.in_(list(version_ids)))
    )
    # `UUID(raw)` without a guard: `AgentSpec.model_profile_id` is typed, so what
    # is frozen into the JSONB has already been through Pydantic. A malformed id
    # cannot be published, and a branch for one would be a branch nothing reaches.
    return {version_id: UUID(raw) for version_id, raw in result.all() if raw is not None}


async def published_compaction_windows(
    db: AsyncSession, *, version_ids: Sequence[UUID]
) -> dict[UUID, int]:
    """The window each version's `compaction` binding overrides its model's with.

    An author sets this when the resolved window is wrong - the pricing registry
    records 1,000,000 for `anthropic:claude-sonnet-4-5` against a real 200,000 -
    or when they want the trigger to allow for the instructions and tool schemas
    the compaction estimator does not count. Either way it is the number the
    *trigger* uses, so it has to be the number the gauge divides by: two figures
    describing one ceiling, disagreeing, is what this whole area kept producing.

    The capability array rather than one path, because the binding is an entry in
    a list and JSONB has no readable way to filter one out. It is a handful of
    small objects beside instructions that run to kilobytes.

    Absent where no compaction binding is published, or where it sets no
    override; the caller then falls back to the model's own window.
    """
    if not version_ids:
        return {}
    result = await db.execute(
        select(AgentVersion.id, AgentVersion.spec["capabilities"]).where(
            AgentVersion.id.in_(list(version_ids))
        )
    )
    found: dict[UUID, int] = {}
    for version_id, bindings in result.all():
        for binding in bindings or []:
            if binding.get("id") != "compaction":
                continue
            window = (binding.get("config") or {}).get("context_window")
            if isinstance(window, int):
                found[version_id] = window
    return found


async def list_all_published(db: AsyncSession) -> list[Agent]:
    """Every published agent on the deployment, whoever owns it.

    Deliberately unscoped, like :func:`app.repositories.organization.list_all`,
    and for the same narrow reason: work that is *about* the deployment rather
    than about a tenant. The only caller is the scheduled usage report, which has
    no member to scope to and must reach every organization's agents to know
    which of them asked for one. Grep for this function when auditing
    cross-tenant reads.

    Published only. A draft has no audience that agreed to hear from it - its
    notification settings have not been published either - and archived agents
    are not running.
    """
    result = await db.execute(
        select(Agent).where(Agent.status == AgentStatus.PUBLISHED.value).order_by(Agent.created_at)
    )
    return list(result.scalars().all())


async def list_current_versions(db: AsyncSession) -> list[tuple[Agent, AgentVersion]]:
    """Every published agent paired with its default (current) version.

    Deliberately unscoped, like :func:`list_all_published`, and for the same
    narrow reason: the callers are deployment-wide, not tenant-scoped. Grep for
    this function when auditing cross-tenant reads.

    This is only the *default* pointer. A surface that names no environment runs
    `current_version_id`, but a named environment can pin any other published
    version and a parent can pin a delegate version - so this is one seed of the
    runnable set, not all of it. See :func:`list_environment_versions`.

    Published only. A draft has no frozen version to run, and an archived agent
    refuses new runs - neither can hand a skill to anybody directly.
    """
    result = await db.execute(
        select(Agent, AgentVersion)
        .join(AgentVersion, AgentVersion.id == Agent.current_version_id)
        .where(Agent.status == AgentStatus.PUBLISHED.value)
        .order_by(Agent.organization_id, Agent.slug)
    )
    return list(result.tuples().all())


async def list_environment_versions(db: AsyncSession) -> list[tuple[Agent, AgentVersion]]:
    """Every version a named environment of a published agent pins.

    Unscoped, for the same reason as :func:`list_current_versions`, and its
    companion in the `audit-skill-bindings` sweep: publishing moves only the
    *default* environment, so a "production" environment can stay pinned to an
    older version that `current_version_id` no longer names. A run that targets
    that environment loads exactly this version, so the sweep must see it too.

    Published agents only, because an archived or draft agent refuses a run that
    targets it directly. A version reachable only as a *delegate* is a different
    path - pinned by version id from a parent's spec, followed by the caller.
    """
    result = await db.execute(
        select(Agent, AgentVersion)
        .join(AgentEnvironment, AgentEnvironment.agent_id == Agent.id)
        .join(AgentVersion, AgentVersion.id == AgentEnvironment.version_id)
        .where(Agent.status == AgentStatus.PUBLISHED.value)
        .order_by(Agent.organization_id, Agent.slug)
    )
    return list(result.tuples().all())


async def list_active_run_versions(db: AsyncSession) -> list[tuple[Agent, AgentVersion]]:
    """Every version a non-terminal run still loads, each with its agent.

    The third seed of the runnable set, beside :func:`list_current_versions` and
    :func:`list_environment_versions`, and unscoped for the same reason: the
    `audit-skill-bindings` sweep is deployment-wide. A run records the version it
    executed in `agent_version_id`, and a run that has not ended still loads it: a
    `running` run is executing it now, and an `awaiting_approval` run reloads it
    when :meth:`AgentRunnerService.resume` continues it. The five terminal states -
    `completed`, `failed`, `cancelled`, `budget_exceeded` and `guardrail_blocked` -
    never load it again, so there `agent_version_id` is only a historical record.
    A parked run resumes only from stored `paused_state`; one without it can never
    continue, so it is excluded rather than seeding a version no resume can reach.

    Unlike the two companion seeds this does **not** filter to published agents.
    `resume` re-assembles the parked version through `registry.get`, which checks
    the agent exists and the caller may run it but not its status - so a run parked
    before its agent was archived still resumes and still hands out that version's
    skills. The join to `AgentVersion` drops a run whose version was deleted
    (`agent_version_id` is `SET NULL`): there is then nothing left to reload.

    A hot version with many live runs is returned once per run; the sweep
    deduplicates by version id, exactly as it does for the default environment
    appearing in both companion seeds.
    """
    result = await db.execute(
        select(Agent, AgentVersion)
        .select_from(AgentRun)
        .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(
            or_(
                AgentRun.status == RunStatus.RUNNING.value,
                and_(
                    AgentRun.status == RunStatus.AWAITING_APPROVAL.value,
                    AgentRun.paused_state.isnot(None),
                ),
            )
        )
    )
    return list(result.tuples().all())


async def get_versions_with_agents(
    db: AsyncSession, version_ids: Sequence[UUID]
) -> list[tuple[Agent, AgentVersion]]:
    """Specific versions, each with its agent, whoever owns them.

    Unscoped and by id: the caller is the sweep resolving `SubagentRef` pins,
    which name a delegate version directly and cross no organization boundary a
    tenant filter could express. A pure fetch that does not filter on the agent's
    status - the agent is returned alongside precisely so the caller can apply the
    runtime's own rule, which refuses to delegate to an archived agent
    (`_resolve_delegate` in `agent_runner.py`).
    """
    if not version_ids:
        return []
    result = await db.execute(
        select(Agent, AgentVersion)
        .select_from(AgentVersion)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersion.id.in_(list(version_ids)))
    )
    return list(result.tuples().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    slug: str,
    name: str,
    description: str | None,
    draft_spec: dict,
    owner_user_id: UUID | None,
    created_by_user_id: UUID | None,
) -> Agent:
    agent = Agent(
        organization_id=organization_id,
        slug=slug,
        name=name,
        description=description,
        draft_spec=draft_spec,
        owner_user_id=owner_user_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def update(db: AsyncSession, *, agent: Agent, update_data: dict) -> Agent:
    for field, value in update_data.items():
        setattr(agent, field, value)
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    return agent


async def delete(db: AsyncSession, agent: Agent) -> None:
    await db.delete(agent)
    await db.flush()


async def next_version_number(db: AsyncSession, *, agent_id: UUID) -> int:
    """The next version number for an agent, starting at 1."""
    current = await db.scalar(
        select(func.max(AgentVersion.version)).where(AgentVersion.agent_id == agent_id)
    )
    return (current or 0) + 1


async def create_version(
    db: AsyncSession,
    *,
    agent_id: UUID,
    organization_id: UUID,
    version: int,
    spec: dict,
    note: str | None,
    published_by_user_id: UUID | None,
) -> AgentVersion:
    row = AgentVersion(
        agent_id=agent_id,
        organization_id=organization_id,
        version=version,
        spec=spec,
        note=note,
        published_by_user_id=published_by_user_id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_version(
    db: AsyncSession, version_id: UUID, *, organization_id: UUID
) -> AgentVersion | None:
    result = await db.execute(
        select(AgentVersion).where(
            AgentVersion.id == version_id,
            AgentVersion.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    db: AsyncSession, *, agent_id: UUID, organization_id: UUID, skip: int = 0, limit: int = 25
) -> list[AgentVersion]:
    """One page of an agent's publication history, newest first."""
    result = await db.execute(
        select(AgentVersion)
        .where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.organization_id == organization_id,
        )
        .order_by(AgentVersion.version.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_for_organization(db: AsyncSession, *, organization_id: UUID) -> int:
    """How many agents this organization holds, archived ones excluded.

    Archiving is how an agent is retired, so a ceiling a retired agent went on
    occupying would make the only way back under it a delete - and a delete takes
    the version history and the run attribution with it.
    """
    result = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.organization_id == organization_id,
            Agent.status != AgentStatus.ARCHIVED.value,
        )
    )
    return int(result.scalar_one())


async def count_versions(db: AsyncSession, *, agent_id: UUID, organization_id: UUID) -> int:
    """How many versions there are, which is not how many were returned.

    The listing used to cap at fifty with no offset and report `total` as the
    length of what it returned, so an agent published sixty times said it had
    fifty versions and the ten oldest were unreachable - including whichever one
    an environment is still pinned to.
    """
    result = await db.execute(
        select(func.count())
        .select_from(AgentVersion)
        .where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.organization_id == organization_id,
        )
    )
    return int(result.scalar_one())
