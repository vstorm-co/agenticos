"""Artifact repository (PostgreSQL async).

Listing is scoped the way every shared resource is: `list_visible` takes the
predicate pieces the access layer resolved rather than re-deriving them, the
shape `context_repo` and `skill_repo` use.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, false, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.artifact import Artifact, ArtifactFollower, ArtifactVersion
from app.db.models.resource_grant import Visibility
from app.repositories._search import contains_ci


async def get(db: AsyncSession, artifact_id: UUID, *, organization_id: UUID) -> Artifact | None:
    result = await db.execute(
        select(Artifact).where(
            Artifact.id == artifact_id, Artifact.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


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


def _visible(
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    shared_with_me: bool,
) -> list[Any]:
    """Which rows one member may see - the predicate the list and its filters share."""
    where: list[Any] = [Artifact.organization_id == organization_id]
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
    search: str | None = None,
    agent_id: UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Artifact], int]:
    """The artifacts one member may see, newest publication first, with the total.

    Args:
        see_all: True when the caller's role reaches the whole organization.
        shared_ids: Artifact ids explicitly shared with this member.
        shared_with_me: Narrow to rows shared with the caller and not their own.
        agent_id: Narrow to one agent's pages, on top of the visibility rules.
    """
    where = _visible(
        organization_id=organization_id,
        user_id=user_id,
        see_all=see_all,
        shared_ids=shared_ids,
        shared_with_me=shared_with_me,
    )
    if search:
        where.append(or_(contains_ci(Artifact.title, search), contains_ci(Artifact.name, search)))
    if agent_id is not None:
        where.append(Artifact.agent_id == agent_id)
    items = await db.execute(
        select(Artifact)
        .where(*where)
        .order_by(Artifact.published_at.desc(), Artifact.name.asc())
        .offset(skip)
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
) -> list[tuple[UUID, str]]:
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
        select(Agent.id, Agent.name)
        .join(Artifact, Artifact.agent_id == Agent.id)
        .where(*where)
        .distinct()
        .order_by(Agent.name.asc(), Agent.id.asc())
    )
    return [(row[0], row[1]) for row in result.all()]


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
) -> ArtifactVersion:
    version = ArtifactVersion(
        artifact_id=artifact_id,
        number=number,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        storage_path=storage_path,
        run_id=run_id,
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)
    return version


async def versions_beyond(
    db: AsyncSession, artifact_id: UUID, *, keep: int, pinned: int | None = None
) -> list[ArtifactVersion]:
    """Every version older than the newest `keep` - what pruning removes.

    `pinned` is a version number the public link shows, which is never among
    them however old it is.
    """
    result = await db.execute(
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.number.desc())
        .offset(keep)
    )
    return [version for version in result.scalars().all() if version.number != pinned]


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
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id).with_for_update())
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
