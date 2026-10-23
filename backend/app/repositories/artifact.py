"""Artifact repository (PostgreSQL async).

Listing is scoped the way every shared resource is: `list_visible` takes the
predicate pieces the access layer resolved rather than re-deriving them, the
shape `context_repo` and `skill_repo` use.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, false, func, or_, select, true
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Scope
from app.db.models.agent import Agent
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun
from app.db.models.artifact import (
    SERVED_STATES,
    Artifact,
    ArtifactFollower,
    ArtifactVersion,
    ConsentState,
)
from app.db.models.conversation import Conversation
from app.db.models.resource_grant import Visibility
from app.repositories._search import contains_ci


async def get_many(
    db: AsyncSession, artifact_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, Artifact]:
    """Several apps at once, by id, inside one organization."""
    if not artifact_ids:
        return {}
    result = await db.execute(
        select(Artifact).where(
            Artifact.id.in_(list(artifact_ids)), Artifact.organization_id == organization_id
        )
    )
    return {artifact.id: artifact for artifact in result.scalars().all()}


async def get(db: AsyncSession, artifact_id: UUID, *, organization_id: UUID) -> Artifact | None:
    result = await db.execute(
        select(Artifact).where(
            Artifact.id == artifact_id, Artifact.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def get_by_ids(
    db: AsyncSession, artifact_ids: Sequence[UUID], *, organization_id: UUID
) -> list[Artifact]:
    """The artifacts among `artifact_ids` that belong to the organization."""
    if not artifact_ids:
        return []
    result = await db.execute(
        select(Artifact).where(
            Artifact.id.in_(artifact_ids), Artifact.organization_id == organization_id
        )
    )
    return list(result.scalars())


def _identity(
    organization_id: UUID, agent_id: UUID, environment_id: UUID | None, name: str
) -> list[Any]:
    """The predicate naming one artifact: its agent, its environment and its name.

    `IS NULL` for the default environment rather than `=`, which a null never
    satisfies.
    """
    return [
        Artifact.organization_id == organization_id,
        Artifact.agent_id == agent_id,
        Artifact.environment_id.is_(None)
        if environment_id is None
        else Artifact.environment_id == environment_id,
        Artifact.name == name,
    ]


async def get_by_identity(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    environment_id: UUID | None,
    name: str,
) -> Artifact | None:
    """The artifact a run of this agent in this environment knows by this name."""
    result = await db.execute(
        select(Artifact).where(*_identity(organization_id, agent_id, environment_id, name))
    )
    return result.scalar_one_or_none()


async def get_for_update(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    environment_id: UUID | None,
    name: str,
) -> Artifact | None:
    """The artifact a publish writes to, locked until the transaction ends.

    Locked because two runs of one agent publishing the same name at once would
    otherwise both read version 7 as the newest and both try to write 8.
    """
    result = await db.execute(
        select(Artifact)
        .where(*_identity(organization_id, agent_id, environment_id, name))
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_by_public_key(db: AsyncSession, public_key: str) -> Artifact | None:
    result = await db.execute(select(Artifact).where(Artifact.public_key == public_key))
    return result.scalar_one_or_none()


def _editable(*, user_id: UUID, scope: Scope, grant_ids: list[UUID]) -> ColumnElement[bool]:
    """The rows `artifacts:edit` reaches for one member: their role's scope, or a grant.

    The SQL form of `access._scope_allows` plus an edit grant, for a listing that
    has to page over rows only an editor may see.
    """
    owner = Artifact.owner_user_id == user_id
    reach: list[ColumnElement[bool]] = [Artifact.id.in_(grant_ids)] if grant_ids else []
    if scope is Scope.ALL:
        return true()
    if scope is Scope.TEAM:
        reach.append(
            or_(owner, Artifact.visibility.in_([Visibility.TEAM.value, Visibility.ORG.value]))
        )
    elif scope is Scope.SHARED:
        reach.append(or_(owner, Artifact.visibility == Visibility.ORG.value))
    elif scope is Scope.OWN:
        reach.append(owner)
    return or_(*reach) if reach else false()


def _visible(
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    shared_with_me: bool,
    include_archived: bool = False,
    archived_reach: ColumnElement[bool] = false(),
) -> list[Any]:
    """Which rows one member may see - the predicate the list and its filters share.

    Archived pages only when asked for, and then only those `archived_reach` admits:
    none of them serves anything, and one exists only for the members who can edit it.
    """
    where: list[Any] = [Artifact.organization_id == organization_id]
    if not include_archived:
        where.append(Artifact.archived_at.is_(None))
    else:
        where.append(or_(Artifact.archived_at.is_(None), archived_reach))
    if shared_with_me:
        where.append(
            and_(
                or_(
                    Artifact.visibility == Visibility.ORG.value,
                    Artifact.id.in_(shared_ids) if shared_ids else false(),
                ),
                Artifact.owner_user_id.is_distinct_from(user_id),
            )
        )
    elif not see_all:
        where.append(
            or_(
                Artifact.owner_user_id == user_id,
                Artifact.visibility == Visibility.ORG.value,
                Artifact.id.in_(shared_ids) if shared_ids else false(),
            )
        )
    return where


async def list_visible(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    shared_with_me: bool = False,
    include_archived: bool = False,
    edit_scope: Scope = Scope.NONE,
    edit_ids: list[UUID] | None = None,
    search: str | None = None,
    agent_id: UUID | None = None,
    only_ids: Sequence[UUID] | None = None,
    project_id: UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Artifact], int]:
    """The artifacts one member may see, newest publication first, with the total.

    Args:
        see_all: True when the caller's role reaches the whole organization.
        shared_ids: Artifact ids explicitly shared with this member.
        shared_with_me: Narrow to rows shared with the caller and not their own.
        include_archived: List archived pages too; they are left out otherwise.
        edit_scope: The scope of the caller's `artifacts:edit`, and `edit_ids` the pages
            an edit grant gives them: of the archived pages only those they may edit are
            listed.
        agent_id: Narrow to one agent's pages, on top of the visibility rules.
        only_ids: Narrow to these rows - the pages shared with one group.
        project_id: Narrow to the pages a run in one of this project's chats
            published a version of, on top of the visibility rules.
    """
    where = _visible(
        organization_id=organization_id,
        user_id=user_id,
        see_all=see_all,
        shared_ids=shared_ids,
        shared_with_me=shared_with_me,
        include_archived=include_archived,
        archived_reach=_editable(user_id=user_id, scope=edit_scope, grant_ids=edit_ids or []),
    )
    if search:
        where.append(or_(contains_ci(Artifact.title, search), contains_ci(Artifact.name, search)))
    if agent_id is not None:
        where.append(Artifact.agent_id == agent_id)
    if only_ids is not None:
        where.append(Artifact.id.in_(only_ids))
    if project_id is not None:
        # Through the versions, not the artifact: a page is the project's when
        # any version of it was written there, the way a chat in the project
        # points at the version its run published.
        where.append(
            Artifact.id.in_(
                select(ArtifactVersion.artifact_id)
                .join(AgentRun, AgentRun.id == ArtifactVersion.run_id)
                .join(Conversation, Conversation.id == AgentRun.conversation_id)
                .where(Conversation.project_id == project_id)
            )
        )
    items = await db.execute(
        select(Artifact)
        .where(*where)
        .order_by(Artifact.published_at.desc(), Artifact.name.asc())
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count(Artifact.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def list_for_agent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    environment_id: UUID | None,
    reader_id: UUID,
    member: bool,
    room: bool,
    see_all: bool,
    shared_ids: list[UUID],
    limit: int,
) -> tuple[list[Artifact], int]:
    """One agent's pages in one environment that a run's reader may see, newest first.

    Args:
        member: Whether the reader is an active member. One who is not keeps only
            their own pages - and in a room only those of them that are
            organization-wide.
        room: The run is read by a group chat, so only what the whole
            organization may see is listed: organization-wide pages. Never the
            reader's private or team pages, nor one shared with the reader alone.
        see_all: The reader's role reaches every page. Ignored in a room.
        shared_ids: Pages explicitly shared with the reader. Ignored in a room.

    An archived page is never listed: to a run it is not there.
    """
    where: list[Any] = [
        Artifact.organization_id == organization_id,
        Artifact.archived_at.is_(None),
        Artifact.agent_id == agent_id,
        Artifact.environment_id.is_(None)
        if environment_id is None
        else Artifact.environment_id == environment_id,
    ]
    own = Artifact.owner_user_id == reader_id
    org_wide = Artifact.visibility == Visibility.ORG.value
    shared = Artifact.id.in_(shared_ids) if shared_ids else false()
    if not member:
        where.extend([own, org_wide] if room else [own])
    elif room:
        where.append(org_wide)
    elif not see_all:
        where.append(or_(own, org_wide, shared))
    items = await db.execute(
        select(Artifact)
        .where(*where)
        .order_by(Artifact.published_at.desc(), Artifact.name.asc())
        .limit(limit)
    )
    total = await db.scalar(select(func.count(Artifact.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def publishing_agents(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
) -> list[Agent]:
    """The agents behind the artifacts one member may see, by name - an agent filter's options.

    Named through the artifacts rather than the agents the member may open: a page
    shared with somebody shows who published it, and the filter offers exactly the
    publishers the list can contain.
    """
    where = _visible(
        organization_id=organization_id,
        user_id=user_id,
        see_all=see_all,
        shared_ids=shared_ids,
        shared_with_me=False,
    )
    result = await db.execute(
        select(Agent)
        .join(Artifact, Artifact.agent_id == Agent.id)
        .where(*where)
        .distinct()
        .order_by(Agent.name.asc(), Agent.id.asc())
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
    agent_id: UUID,
    environment_id: UUID | None,
    name: str,
    title: str,
) -> Artifact:
    artifact = Artifact(
        organization_id=organization_id,
        owner_user_id=owner_user_id,
        agent_id=agent_id,
        environment_id=environment_id,
        name=name,
        title=title,
        visibility=Visibility.PRIVATE.value,
    )
    db.add(artifact)
    await db.flush()
    await db.refresh(artifact)
    return artifact


async def update(db: AsyncSession, *, artifact: Artifact, update_data: dict[str, Any]) -> Artifact:
    for field, value in update_data.items():
        setattr(artifact, field, value)
    db.add(artifact)
    await db.flush()
    await db.refresh(artifact)
    return artifact


async def delete_artifact(db: AsyncSession, artifact: Artifact) -> None:
    await db.delete(artifact)
    await db.flush()


async def count_public_view(db: AsyncSession, artifact_id: UUID, *, at: datetime) -> None:
    """Count one opening of the public link, in the database rather than in Python.

    An `UPDATE ... SET n = n + 1`, so two visitors at once are two views and not
    one read-modify-write that lost the other.
    """
    await db.execute(
        sql_update(Artifact)
        .where(Artifact.id == artifact_id)
        .values(
            public_view_count=Artifact.public_view_count + 1,
            public_last_viewed_at=at,
        )
    )
    await db.flush()


async def detach_environment(db: AsyncSession, *, environment_id: UUID) -> None:
    """Leave an environment's artifacts readable with no publisher, before it is deleted.

    The environment's foreign key would null `environment_id` and drop the page
    into the default environment's slot, where a page of the same name may already
    be. Nulling `agent_id` as well is what deleting an agent does to its pages.
    """
    await db.execute(
        sql_update(Artifact)
        .where(Artifact.environment_id == environment_id)
        .values(agent_id=None, environment_id=None)
    )
    await db.flush()


async def latest_version(db: AsyncSession, artifact_id: UUID) -> ArtifactVersion | None:
    result = await db.execute(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.number.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_versions(
    db: AsyncSession, artifact_ids: list[UUID]
) -> dict[UUID, ArtifactVersion]:
    """The current version of each artifact, in one query for a whole listing page."""
    if not artifact_ids:
        return {}
    newest = (
        select(
            ArtifactVersion.artifact_id,
            func.max(ArtifactVersion.number).label("number"),
        )
        .where(ArtifactVersion.artifact_id.in_(artifact_ids))
        .group_by(ArtifactVersion.artifact_id)
        .subquery()
    )
    result = await db.execute(
        select(ArtifactVersion).join(
            newest,
            and_(
                ArtifactVersion.artifact_id == newest.c.artifact_id,
                ArtifactVersion.number == newest.c.number,
            ),
        )
    )
    return {version.artifact_id: version for version in result.scalars().all()}


async def latest_served(db: AsyncSession, artifact_id: UUID) -> ArtifactVersion | None:
    """The newest version that is consented or reads no data - what the audience is served."""
    result = await db.execute(
        select(ArtifactVersion)
        .where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.consent_state.in_(SERVED_STATES),
        )
        .order_by(ArtifactVersion.number.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_served_versions(
    db: AsyncSession, artifact_ids: list[UUID]
) -> dict[UUID, ArtifactVersion]:
    """:func:`latest_served` for each artifact, in one query for a whole listing page."""
    if not artifact_ids:
        return {}
    newest = (
        select(
            ArtifactVersion.artifact_id,
            func.max(ArtifactVersion.number).label("number"),
        )
        .where(
            ArtifactVersion.artifact_id.in_(artifact_ids),
            ArtifactVersion.consent_state.in_(SERVED_STATES),
        )
        .group_by(ArtifactVersion.artifact_id)
        .subquery()
    )
    result = await db.execute(
        select(ArtifactVersion).join(
            newest,
            and_(
                ArtifactVersion.artifact_id == newest.c.artifact_id,
                ArtifactVersion.number == newest.c.number,
            ),
        )
    )
    return {version.artifact_id: version for version in result.scalars().all()}


async def served_before(db: AsyncSession, artifact_id: UUID, number: int) -> ArtifactVersion | None:
    """The newest version older than `number` that the audience could be served."""
    result = await db.execute(
        select(ArtifactVersion)
        .where(
            ArtifactVersion.artifact_id == artifact_id,
            ArtifactVersion.number < number,
            ArtifactVersion.consent_state.in_(SERVED_STATES),
        )
        .order_by(ArtifactVersion.number.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def latest_consent(
    db: AsyncSession, artifact_id: UUID, *, membership_id: UUID, after: datetime | None
) -> ArtifactVersion | None:
    """The newest version consented under this membership after `after`, a withdrawal.

    `None` for `after` when nothing was ever withdrawn.
    """
    where: list[Any] = [
        ArtifactVersion.artifact_id == artifact_id,
        ArtifactVersion.consent_state == ConsentState.CONSENTED.value,
        ArtifactVersion.consented_by_membership_id == membership_id,
    ]
    if after is not None:
        where.append(ArtifactVersion.consented_at > after)
    result = await db.execute(
        select(ArtifactVersion).where(*where).order_by(ArtifactVersion.number.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def update_version(
    db: AsyncSession, *, version: ArtifactVersion, update_data: dict[str, Any]
) -> ArtifactVersion:
    for field, value in update_data.items():
        setattr(version, field, value)
    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


async def get_version(
    db: AsyncSession, version_id: UUID, *, artifact_id: UUID | None = None
) -> ArtifactVersion | None:
    where = [ArtifactVersion.id == version_id]
    if artifact_id is not None:
        where.append(ArtifactVersion.artifact_id == artifact_id)
    result = await db.execute(select(ArtifactVersion).where(*where))
    return result.scalar_one_or_none()


async def get_version_with_artifact(
    db: AsyncSession, version_id: UUID
) -> tuple[ArtifactVersion, Artifact] | None:
    """A version and the artifact it belongs to, by the version's id alone.

    Unscoped by organization on purpose: the only caller holds a token this
    deployment signed for exactly this version, and the tenant was checked when
    it was minted.
    """
    result = await db.execute(
        select(ArtifactVersion, Artifact)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(ArtifactVersion.id == version_id)
    )
    row = result.one_or_none()
    return None if row is None else (row[0], row[1])


async def list_versions(db: AsyncSession, artifact_id: UUID) -> list[ArtifactVersion]:
    result = await db.execute(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.number.desc())
    )
    return list(result.scalars().all())


async def create_version(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    number: int,
    media_type: str,
    size_bytes: int,
    sha256: str,
    storage_path: str,
    run_id: UUID | None,
    bindings: list[dict[str, Any]],
    actions: list[dict[str, Any]] | None = None,
    restored_from: int | None = None,
    consent: dict[str, Any] | None = None,
) -> ArtifactVersion:
    """A new version row. `consent` holds its publisher and consent columns by name."""
    version = ArtifactVersion(
        artifact_id=artifact_id,
        number=number,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        storage_path=storage_path,
        run_id=run_id,
        bindings=bindings,
        actions=actions or [],
        restored_from=restored_from,
        **(consent or {}),
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


async def versions_beyond(
    db: AsyncSession,
    artifact_id: UUID,
    *,
    keep: int,
    kept: Collection[int] = (),
) -> list[ArtifactVersion]:
    """Every version older than the newest `keep` - what pruning removes.

    `kept` are version numbers that stay however old they are: the one the public
    link shows, the one the page's audience is served and the one a republish's
    consent is compared against.
    """
    result = await db.execute(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.number.desc())
        .offset(keep)
    )
    return [version for version in result.scalars().all() if version.number not in kept]


async def get_version_by_number(
    db: AsyncSession, artifact_id: UUID, number: int
) -> ArtifactVersion | None:
    result = await db.execute(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact_id, ArtifactVersion.number == number
        )
    )
    return result.scalar_one_or_none()


async def delete_versions(db: AsyncSession, version_ids: list[UUID]) -> None:
    if not version_ids:
        return
    await db.execute(delete(ArtifactVersion).where(ArtifactVersion.id.in_(version_ids)))
    await db.flush()


async def storage_paths(db: AsyncSession, artifact_id: UUID) -> list[str]:
    result = await db.execute(
        select(ArtifactVersion.storage_path).where(ArtifactVersion.artifact_id == artifact_id)
    )
    return list(result.scalars().all())


async def lock(db: AsyncSession, artifact_id: UUID) -> Artifact | None:
    """The artifact locked until the transaction ends, for a write that adds a version."""
    result = await db.execute(
        select(Artifact)
        .where(Artifact.id == artifact_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def environment_names(db: AsyncSession, environment_ids: list[UUID]) -> dict[UUID, str]:
    """The names of the environments a page of artifacts was published in."""
    if not environment_ids:
        return {}
    result = await db.execute(
        select(AgentEnvironment.id, AgentEnvironment.name).where(
            AgentEnvironment.id.in_(environment_ids)
        )
    )
    return {row[0]: row[1] for row in result.all()}


async def follow(db: AsyncSession, *, artifact_id: UUID, user_id: UUID) -> None:
    """Add a follower; following twice is following once."""
    await db.execute(
        pg_insert(ArtifactFollower)
        .values(artifact_id=artifact_id, user_id=user_id)
        .on_conflict_do_nothing(constraint="uq_artifact_follower")
    )
    await db.flush()


async def unfollow(db: AsyncSession, *, artifact_id: UUID, user_id: UUID) -> None:
    await db.execute(
        delete(ArtifactFollower).where(
            ArtifactFollower.artifact_id == artifact_id, ArtifactFollower.user_id == user_id
        )
    )
    await db.flush()


async def is_following(db: AsyncSession, *, artifact_id: UUID, user_id: UUID) -> bool:
    result = await db.execute(
        select(ArtifactFollower.id).where(
            ArtifactFollower.artifact_id == artifact_id, ArtifactFollower.user_id == user_id
        )
    )
    return result.first() is not None


async def follower_ids(db: AsyncSession, artifact_id: UUID) -> list[UUID]:
    result = await db.execute(
        select(ArtifactFollower.user_id)
        .where(ArtifactFollower.artifact_id == artifact_id)
        .order_by(ArtifactFollower.created_at)
    )
    return list(result.scalars().all())
