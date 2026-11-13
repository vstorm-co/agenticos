"""Audit log repository (PostgreSQL async)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, and_, case, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import UserDefinedType

from app.db.models.audit_checkpoint import AppAdminAuditCheckpoint
from app.db.models.audit_log import AppAdminAuditLog


async def installed_skill_keys(db: AsyncSession, *, organization_id: UUID) -> set[str]:
    """Installation receipts survive skill deletion, so upgrades respect retirement."""
    keys = await db.scalars(
        select(AppAdminAuditLog.details["key"].astext)
        .where(
            AppAdminAuditLog.organization_id == organization_id,
            AppAdminAuditLog.action == "skill.installed",
        )
        .distinct()
    )
    return {key for key in keys if key is not None}


async def list_for_org(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 50,
) -> list[AppAdminAuditLog]:
    """One organization's audit entries, newest first."""
    result = await db.execute(
        select(AppAdminAuditLog)
        .where(AppAdminAuditLog.organization_id == organization_id)
        .order_by(AppAdminAuditLog.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def count_for_org(db: AsyncSession, *, organization_id: UUID) -> int:
    result = await db.scalar(
        select(func.count())
        .select_from(AppAdminAuditLog)
        .where(AppAdminAuditLog.organization_id == organization_id)
    )
    return result or 0


async def list_in_window_for_org(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
    until: datetime,
    limit: int,
) -> tuple[list[AppAdminAuditLog], int]:
    """One organization's entries in a closed date window, newest first, and the
    total in that window.

    The total is `count(*) OVER()` on the same statement as the rows, not a
    separate query: the caller caps the fetch at `limit` and refuses above the
    total, and two statements under READ COMMITTED could see different snapshots -
    a count of 10,000 then a select over 10,001 - so the export would truncate to
    the cap where it promised to refuse. A window function is evaluated before the
    LIMIT, so the total is the whole match and the rows are its first `limit`, from
    one snapshot.
    """
    where = (
        AppAdminAuditLog.organization_id == organization_id,
        AppAdminAuditLog.created_at >= since,
        AppAdminAuditLog.created_at <= until,
    )
    result = await db.execute(
        select(AppAdminAuditLog, func.count().over().label("total"))
        .where(*where)
        .order_by(AppAdminAuditLog.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    total = rows[0].total if rows else 0
    return [row[0] for row in rows], total


async def distinct_organization_ids(db: AsyncSession) -> list[UUID | None]:
    """Every chain the log holds - one organization id per chain, and `None` for
    the deployment-wide chain when it has any entries. This is the set
    `audit-verify` walks when no organization is named."""
    result = await db.execute(select(AppAdminAuditLog.organization_id).distinct())
    return list(result.scalars().all())


async def chain_for_org(
    db: AsyncSession, *, organization_id: UUID | None
) -> list[AppAdminAuditLog]:
    """One chain's entries in the order they link - `seq` ascending. `None` reads
    the deployment-wide chain, whose entries carry no organization."""
    condition = (
        AppAdminAuditLog.organization_id.is_(None)
        if organization_id is None
        else AppAdminAuditLog.organization_id == organization_id
    )
    result = await db.execute(
        select(AppAdminAuditLog).where(condition).order_by(AppAdminAuditLog.seq.asc())
    )
    return list(result.scalars().all())


async def checkpoint_for_org(
    db: AsyncSession, *, organization_id: UUID | None
) -> AppAdminAuditCheckpoint | None:
    """This chain's high-water mark, or None if it has never been checkpointed.
    `None` reads the deployment-wide chain's checkpoint."""
    condition = (
        AppAdminAuditCheckpoint.organization_id.is_(None)
        if organization_id is None
        else AppAdminAuditCheckpoint.organization_id == organization_id
    )
    result = await db.execute(select(AppAdminAuditCheckpoint).where(condition))
    return result.scalar_one_or_none()


async def distinct_checkpoint_organization_ids(db: AsyncSession) -> list[UUID | None]:
    """Every organization that has a checkpoint - the set `audit-verify` adds so a
    chain deleted whole (no entries left, but a checkpoint remaining) is still
    walked."""
    result = await db.execute(select(AppAdminAuditCheckpoint.organization_id).distinct())
    return list(result.scalars().all())


class _PgType(UserDefinedType):
    """A PostgreSQL type named only to cast to it."""

    cache_ok = True

    def __init__(self, name: str) -> None:
        self.name = name

    def get_col_spec(self, **_kw: object) -> str:
        return self.name


_XID8 = _PgType("xid8")
_PG_SNAPSHOT = _PgType("pg_snapshot")


ERASURE_TRANSACTION = "transaction"
"""The key in a memory erasure's audit details naming its cluster and transaction."""

ERASURE_FINISHED = "finished_at"
"""The key in a memory erasure's audit details holding when its deletes were done."""

# Transaction ids and snapshots belong to one PostgreSQL cluster: a dump restored into
# another numbers transactions afresh. Each is stored as `<cluster>/<value>` and only
# compared with a value from the same cluster. Both are null where the database does
# not say which cluster it is (0323_run_memory_snapshot.py), and time decides alone.


async def erasure_marks(db: AsyncSession) -> dict[str, str]:
    """What a memory erasure records once its deletes are done, for `memory_erased_since`."""
    transaction, finished = (
        await db.execute(
            select(
                func.agenticos_memory_cluster()
                .concat("/")
                .concat(cast(func.pg_current_xact_id(), Text)),
                cast(func.clock_timestamp(), Text),
            )
        )
    ).one()
    marks = {ERASURE_FINISHED: str(finished)}
    if transaction is not None:
        marks[ERASURE_TRANSACTION] = str(transaction)
    return marks


async def current_snapshot(db: AsyncSession) -> str | None:
    """The transactions committed now, as a run records them when its row is inserted."""
    snapshot = (await db.execute(select(func.agenticos_memory_snapshot()))).scalar_one()
    return None if snapshot is None else str(snapshot)


def _memory_erasures(user_id: UUID | None, agent_id: UUID | None) -> list:
    erased = []
    if agent_id is not None:
        erased.append(
            and_(
                AppAdminAuditLog.action == "memory.agent.cleared",
                AppAdminAuditLog.target_id == str(agent_id),
            )
        )
    if user_id is not None:
        erased.append(
            and_(
                AppAdminAuditLog.action == "memory.person.forgotten",
                AppAdminAuditLog.target_id == str(user_id),
            )
        )
    return erased


async def memory_erased_since(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    agent_id: UUID | None,
    since: datetime,
    snapshot: str | None = None,
) -> bool:
    """Whether this person's memory, or this agent's, was erased after `since`.

    An erasure writes the trail as it commits, so this is the cutoff a queued read of an
    older conversation must respect: the transcript outlives the erasure, and reading it
    again would put back what the person was just told is gone. Only the erasures of
    the person and the agent given are asked about; with neither there is nothing to ask.

    An erasure's entry is dated when its transaction began, so one still committing when
    the reader began is dated before `since` although the reader saw what it removed.
    `snapshot`, the transactions committed when the reader began, catches it: an
    erasure whose transaction is not in it counts as later, whatever its date. An
    erasure recorded in another cluster, before a restore, is judged by its date alone.
    """
    erased = _memory_erasures(user_id, agent_id)
    if not erased:
        return False
    later = AppAdminAuditLog.created_at > since
    cluster, _, visible = (snapshot or "").partition("/")
    if visible:
        transaction = AppAdminAuditLog.details[ERASURE_TRANSACTION].astext
        # A CASE, so the id is cast only once its cluster is known to be this one.
        uncommitted = case(
            (
                func.split_part(transaction, "/", 1) == cluster,
                ~func.pg_visible_in_snapshot(
                    cast(func.split_part(transaction, "/", 2), _XID8),
                    cast(literal(visible), _PG_SNAPSHOT),
                ),
            ),
            else_=False,
        )
        later = or_(later, uncommitted)
    found = await db.scalar(
        select(AppAdminAuditLog.id)
        .where(AppAdminAuditLog.organization_id == organization_id, later, or_(*erased))
        .limit(1)
    )
    return found is not None


async def latest_memory_erasure(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> datetime | None:
    """When this person's memory in this organization was last erased, if ever.

    The later of the entry's date, from the app's clock, and the database's clock once
    the deletes were done, which is the clock a message is dated on: what the person
    wrote while it ran counts as before it, whatever the two clocks disagree by.
    """
    finished = cast(AppAdminAuditLog.details[ERASURE_FINISHED].astext, DateTime(timezone=True))
    return await db.scalar(
        select(func.max(func.greatest(AppAdminAuditLog.created_at, finished))).where(
            AppAdminAuditLog.organization_id == organization_id,
            or_(*_memory_erasures(user_id, None)),
        )
    )
