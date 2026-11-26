"""The memory ledger's repository (PostgreSQL async).

Every read is scoped to an organization and to named scopes. A scope is a
`(scope_key, agent_id)` pair: `agent_id` set is one agent's relationship with the
scope's owner, null is what every agent acting in that scope may use. Nothing here
reads across scopes it was not handed, so what a run may see is decided once - in
`app.agents.memory_scope` - and not by a filter someone forgot.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, Text, and_, case, func, literal, or_, select, true, tuple_
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.agent import Agent
from app.db.models.mcp_connection import AUTHORIZATION_EXPIRED, McpConnection
from app.db.models.memory_claim import (
    MemoryClaim,
    MemoryClaimEvidence,
    MemoryClaimRevision,
    MemoryMailEvent,
    MemoryMailSource,
    MemoryObject,
    MemoryScopeState,
    SharedMemoryNote,
)
from app.db.models.suggestion import Suggestion


@dataclass(frozen=True)
class ClaimScope:
    """One place claims live: whose they are, and which agent they are bound to."""

    scope_key: str
    agent_id: UUID | None = None


def _texts(values: list[str]) -> Any:
    """A `text[]` operand: `?|` takes one, and a bound list would arrive as `jsonb`."""
    return literal(values, type_=ARRAY(Text))


def _in_effect() -> Any:
    """Claims whose validity covers now: begun, and not yet ended.

    A correction dated for next Monday leaves the old claim true until then and the new one
    unspoken until then; status alone cannot say that, so what is put in front of a model
    is filtered by the interval too.
    """
    now = func.statement_timestamp()
    return and_(
        or_(MemoryClaim.effective_from.is_(None), MemoryClaim.effective_from <= now),
        or_(MemoryClaim.effective_to.is_(None), MemoryClaim.effective_to > now),
    )


def _in_scopes(scopes: Sequence[ClaimScope]) -> Any:
    return or_(
        *(
            and_(
                MemoryClaim.scope_key == scope.scope_key,
                MemoryClaim.agent_id.is_(None)
                if scope.agent_id is None
                else MemoryClaim.agent_id == scope.agent_id,
            )
            for scope in scopes
        )
    )


def readable_mail_source() -> ColumnElement[bool]:
    """A published mail fact stays available only while the same mailbox is authorized."""
    return (
        select(MemoryMailEvent.id)
        .join(MemoryMailSource, MemoryMailSource.organization_id == MemoryMailEvent.organization_id)
        .join(McpConnection, McpConnection.id == MemoryMailSource.grant_id)
        .where(
            MemoryMailEvent.id == MemoryClaim.mail_event_id,
            MemoryMailEvent.organization_id == MemoryClaim.organization_id,
            MemoryMailEvent.grant_id == McpConnection.id,
            MemoryMailSource.authorization_generation == McpConnection.authorization_generation,
            McpConnection.is_enabled.is_(True),
            McpConnection.last_error.is_distinct_from(AUTHORIZATION_EXPIRED),
        )
        .correlate(MemoryClaim)
        .exists()
    )


def _visible() -> ColumnElement[bool]:
    return or_(MemoryClaim.mail_event_id.is_(None), readable_mail_source())


async def get(db: AsyncSession, *, organization_id: UUID, claim_id: UUID) -> MemoryClaim | None:
    result = await db.execute(
        select(MemoryClaim)
        .where(
            MemoryClaim.organization_id == organization_id, MemoryClaim.id == claim_id, _visible()
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def many(
    db: AsyncSession, *, organization_id: UUID, claim_ids: Sequence[UUID]
) -> list[MemoryClaim]:
    if not claim_ids:
        return []
    result = await db.execute(
        select(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id,
            MemoryClaim.id.in_(list(claim_ids)),
            _visible(),
        )
    )
    return list(result.scalars().all())


async def list_in_scopes(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scopes: Sequence[ClaimScope],
    statuses: Sequence[str] = ("current",),
    limit: int = 50,
    skip: int = 0,
    in_effect: bool = False,
) -> list[MemoryClaim]:
    """Claims in the given scopes, newest first; `in_effect` keeps those valid right now."""
    if not scopes:
        return []
    result = await db.execute(
        select(MemoryClaim)
        .where(
            MemoryClaim.organization_id == organization_id,
            _in_scopes(scopes),
            _visible(),
            MemoryClaim.status.in_(list(statuses)),
            _in_effect() if in_effect else true(),
        )
        .order_by(MemoryClaim.observed_at.desc(), MemoryClaim.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_for_owner(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scope_key: str | Sequence[str],
    statuses: Sequence[str],
    skip: int,
    limit: int,
    in_effect: bool = False,
    q: str = "",
    kind: str | None = None,
    scope: str | None = None,
) -> tuple[list[MemoryClaim], int]:
    """Every claim one owner holds in an organization, under any agent, and the total."""
    clause = (
        MemoryClaim.organization_id == organization_id,
        MemoryClaim.scope_key.in_([scope_key] if isinstance(scope_key, str) else scope_key),
        _visible(),
        MemoryClaim.status.in_(list(statuses)),
        _in_effect() if in_effect else true(),
        MemoryClaim.kind == kind if kind else true(),
        MemoryClaim.agent_id.is_(None)
        if scope == "profile"
        else MemoryClaim.agent_id.is_not(None)
        if scope == "agent"
        else true(),
        or_(
            MemoryClaim.statement.icontains(q, autoescape=True),
            MemoryClaim.subject.icontains(q, autoescape=True),
            MemoryClaim.agent_id.in_(
                select(Agent.id).where(Agent.name.icontains(q, autoescape=True))
            ),
        )
        if q
        else true(),
    )
    total = await db.scalar(select(func.count()).select_from(MemoryClaim).where(*clause)) or 0
    result = await db.execute(
        select(MemoryClaim)
        .where(*clause)
        .order_by(MemoryClaim.observed_at.desc(), MemoryClaim.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_owned(
    db: AsyncSession, *, organization_id: UUID, scope_key: str, claim_id: UUID
) -> MemoryClaim | None:
    """One claim, only if it is in this owner's scope - the owner is part of the lookup."""
    result = await db.execute(
        select(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id,
            MemoryClaim.scope_key == scope_key,
            MemoryClaim.id == claim_id,
        )
    )
    return result.scalar_one_or_none()


async def about_subject(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scope: ClaimScope,
    subject: str,
    statuses: Sequence[str] = ("current", "disputed"),
    object_id: UUID | None = None,
) -> list[MemoryClaim]:
    """The claims on one topic and object in one scope, oldest first."""
    result = await db.execute(
        select(MemoryClaim)
        .where(
            MemoryClaim.organization_id == organization_id,
            _in_scopes([scope]),
            MemoryClaim.subject == subject,
            MemoryClaim.object_id == object_id,
            MemoryClaim.status.in_(list(statuses)),
        )
        .order_by(MemoryClaim.observed_at.asc(), MemoryClaim.id.asc())
    )
    return list(result.scalars().all())


async def without_subject(
    db: AsyncSession, *, organization_id: UUID, scope: ClaimScope, object_id: UUID | None = None
) -> list[MemoryClaim]:
    result = await db.execute(
        select(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id,
            _in_scopes([scope]),
            MemoryClaim.subject.is_(None),
            MemoryClaim.object_id == object_id,
            MemoryClaim.status == "current",
        )
    )
    return list(result.scalars().all())


def _at(as_of: datetime | None, known_at: datetime | None) -> ColumnElement[bool]:
    if as_of is None:
        return and_(MemoryClaim.status.in_(("current", "disputed")), _in_effect())

    statuses = ("current", "disputed", "superseded")
    start = MemoryClaim.effective_from
    if known_at is None:
        return and_(
            MemoryClaim.status.in_(statuses),
            start <= as_of,
            or_(MemoryClaim.effective_to.is_(None), MemoryClaim.effective_to > as_of),
        )

    # An old row has no trustworthy state before its last pre-migration change.
    last = (
        select(MemoryClaimRevision.known_from)
        .where(
            MemoryClaimRevision.claim_id == MemoryClaim.id,
            MemoryClaimRevision.known_from <= known_at,
        )
        .order_by(MemoryClaimRevision.known_from.desc())
        .limit(1)
        .correlate(MemoryClaim)
        .scalar_subquery()
    )
    revision = select(MemoryClaimRevision.claim_id).where(
        MemoryClaimRevision.claim_id == MemoryClaim.id,
        MemoryClaimRevision.known_from == last,
        MemoryClaimRevision.status.in_(statuses),
        or_(MemoryClaimRevision.effective_to.is_(None), MemoryClaimRevision.effective_to > as_of),
    )
    return and_(
        start <= as_of,
        or_(
            revision.exists(),
            and_(
                last.is_(None),
                func.coalesce(MemoryClaim.updated_at, MemoryClaim.observed_at) <= known_at,
                MemoryClaim.status.in_(statuses),
                or_(MemoryClaim.effective_to.is_(None), MemoryClaim.effective_to > as_of),
            ),
        ),
    )


async def states_known_at(
    db: AsyncSession,
    *,
    rows: Sequence[MemoryClaim],
    known_at: datetime,
) -> dict[UUID, MemoryClaimRevision]:
    if not rows:
        return {}
    revisions = await db.scalars(
        select(MemoryClaimRevision)
        .where(
            MemoryClaimRevision.claim_id.in_([row.id for row in rows]),
            MemoryClaimRevision.known_from <= known_at,
        )
        .distinct(MemoryClaimRevision.claim_id)
        .order_by(MemoryClaimRevision.claim_id, MemoryClaimRevision.known_from.desc())
    )
    return {row.claim_id: row for row in revisions}


async def search(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scopes: Sequence[ClaimScope],
    terms: Sequence[str],
    limit: int,
    as_of: datetime | None = None,
    known_at: datetime | None = None,
) -> list[MemoryClaim]:
    """Rank matches inside the approved scope and validity window, before limiting."""
    if not scopes or not terms:
        return []
    matches = [
        or_(
            MemoryClaim.statement.icontains(term, autoescape=True),
            MemoryClaim.subject.icontains(term, autoescape=True),
            MemoryClaim.object_id.in_(
                select(MemoryObject.id).where(
                    MemoryObject.organization_id == organization_id,
                    MemoryObject.name.icontains(term, autoescape=True),
                )
            ),
        )
        for term in terms
    ]
    rank = func.num_nonnulls(*(case((match, 1)) for match in matches))
    result = await db.execute(
        select(MemoryClaim)
        .where(
            MemoryClaim.organization_id == organization_id,
            _in_scopes(scopes),
            _visible(),
            _at(as_of, known_at),
            or_(*matches),
        )
        .order_by(
            rank.desc(),
            (MemoryClaim.status == "current").desc(),
            MemoryClaim.observed_at.desc(),
            MemoryClaim.id,
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def put_object(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scope_key: str,
    kind: str,
    name: str,
    identity_key: str,
) -> MemoryObject:
    """Get or create an identity. A stable external key survives a changed label."""
    result = await db.execute(
        pg_insert(MemoryObject)
        .values(
            organization_id=organization_id,
            scope_key=scope_key,
            kind=kind,
            name=name,
            identity_key=identity_key,
        )
        .on_conflict_do_nothing(constraint="uq_memory_objects_identity")
        .returning(MemoryObject)
    )
    found = result.scalar_one_or_none()
    if found is not None:
        return found
    return (
        await db.execute(
            select(MemoryObject).where(
                MemoryObject.organization_id == organization_id,
                MemoryObject.scope_key == scope_key,
                MemoryObject.kind == kind,
                MemoryObject.identity_key == identity_key,
            )
        )
    ).scalar_one()


async def get_object(
    db: AsyncSession, *, organization_id: UUID, object_id: UUID, scope_keys: Sequence[str]
) -> MemoryObject | None:
    return await db.scalar(
        select(MemoryObject).where(
            MemoryObject.organization_id == organization_id,
            MemoryObject.scope_key.in_(scope_keys),
            MemoryObject.id == object_id,
            select(MemoryClaim.id)
            .where(MemoryClaim.object_id == MemoryObject.id, _visible())
            .exists(),
        )
    )


async def list_objects(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scope_keys: Sequence[str],
    kind: str | None,
    q: str,
    cursor: UUID | None,
    limit: int,
) -> list[MemoryObject]:
    result = await db.scalars(
        select(MemoryObject)
        .where(
            MemoryObject.organization_id == organization_id,
            MemoryObject.scope_key.in_(scope_keys),
            MemoryObject.kind == kind if kind else true(),
            MemoryObject.name.icontains(q, autoescape=True) if q else true(),
            MemoryObject.id > cursor if cursor else true(),
            # Erasure and agent removal can leave an identity without any visible source.
            select(MemoryClaim.id)
            .where(MemoryClaim.object_id == MemoryObject.id, _visible())
            .exists(),
        )
        .order_by(MemoryObject.id)
        .limit(limit)
    )
    return list(result)


async def object_claims(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scope_key: str,
    object_id: UUID,
    as_of: datetime | None,
    known_at: datetime | None,
    cursor: UUID | None,
    limit: int,
) -> list[MemoryClaim]:
    cursor_row = (
        select(MemoryClaim.observed_at, MemoryClaim.id)
        .where(
            MemoryClaim.organization_id == organization_id,
            MemoryClaim.scope_key == scope_key,
            MemoryClaim.object_id == object_id,
            MemoryClaim.id == cursor,
        )
        .subquery()
    )
    query = select(MemoryClaim).where(
        MemoryClaim.organization_id == organization_id,
        MemoryClaim.scope_key == scope_key,
        MemoryClaim.object_id == object_id,
        _visible(),
        _at(as_of, known_at) if as_of is not None else true(),
    )
    if cursor is not None:
        query = query.where(
            tuple_(MemoryClaim.observed_at, MemoryClaim.id)
            < select(cursor_row.c.observed_at, cursor_row.c.id).scalar_subquery()
        )
    result = await db.scalars(
        query.order_by(MemoryClaim.observed_at.desc(), MemoryClaim.id.desc()).limit(limit)
    )
    return list(result)


async def agents_in_scope(
    db: AsyncSession, *, organization_id: UUID, scope_key: str
) -> set[UUID | None]:
    """The agents that hold live claims in a scope; `None` stands for the shared ones."""
    result = await db.execute(
        select(MemoryClaim.agent_id)
        .where(
            MemoryClaim.organization_id == organization_id,
            MemoryClaim.scope_key == scope_key,
            MemoryClaim.status.in_(["current", "disputed"]),
        )
        .distinct()
    )
    return set(result.scalars().all())


async def derived_by_key(
    db: AsyncSession, *, organization_id: UUID, scope_key: str, consolidation_key: str
) -> MemoryClaim | None:
    result = await db.execute(
        select(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id,
            MemoryClaim.scope_key == scope_key,
            MemoryClaim.consolidation_key == consolidation_key,
        )
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, **values: Any) -> MemoryClaim:
    claim = MemoryClaim(**values)
    db.add(claim)
    await db.flush()
    await db.refresh(claim)
    db.add(
        MemoryClaimRevision(
            claim_id=claim.id,
            known_from=claim.observed_at,
            status=claim.status,
            effective_to=claim.effective_to,
        )
    )
    await db.flush()
    return claim


async def set_status(
    db: AsyncSession, claim: MemoryClaim, status: str, *, effective_to: datetime | None = None
) -> None:
    if claim.status == status and (effective_to is None or claim.effective_to == effective_to):
        return
    previous = await db.scalar(
        select(MemoryClaimRevision.known_from)
        .where(MemoryClaimRevision.claim_id == claim.id)
        .limit(1)
    )
    if previous is None:
        db.add(
            MemoryClaimRevision(
                claim_id=claim.id,
                known_from=claim.updated_at or claim.observed_at,
                status=claim.status,
                effective_to=claim.effective_to,
            )
        )
    claim.status = status
    if effective_to is not None:
        claim.effective_to = effective_to
    db.add(
        MemoryClaimRevision(
            claim_id=claim.id,
            known_from=datetime.now(UTC),
            status=claim.status,
            effective_to=claim.effective_to,
        )
    )
    db.add(claim)
    await db.flush()


async def bump_revision(db: AsyncSession, *, organization_id: UUID, scope_key: str) -> None:
    """Record that a scope changed, so consolidation knows it has work."""
    statement = pg_insert(MemoryScopeState).values(
        organization_id=organization_id, scope_key=scope_key, revision=1, consolidated_revision=0
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["organization_id", "scope_key"],
            set_={"revision": MemoryScopeState.revision + 1},
        )
    )


async def locked_state(
    db: AsyncSession, *, organization_id: UUID, scope_key: str
) -> MemoryScopeState | None:
    """The scope's change counters, locked so two consolidations cannot interleave."""
    result = await db.execute(
        select(MemoryScopeState)
        .where(
            MemoryScopeState.organization_id == organization_id,
            MemoryScopeState.scope_key == scope_key,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def mark_consolidated(db: AsyncSession, state: MemoryScopeState, revision: int) -> None:
    state.consolidated_revision = revision
    state.consolidated_at = datetime.now(UTC)
    db.add(state)
    await db.flush()


async def scopes_with_changes(db: AsyncSession, *, limit: int) -> list[MemoryScopeState]:
    """Scopes written since they were last consolidated, oldest change first."""
    result = await db.execute(
        select(MemoryScopeState)
        .where(MemoryScopeState.revision > MemoryScopeState.consolidated_revision)
        .limit(limit)
    )
    return list(result.scalars().all())


async def _delete_descendants(
    db: AsyncSession, ids: list[str], *, organization_id: UUID | None = None
) -> int:
    """Remove what was drawn from `ids`, however many copies removed - and only that.

    A claim shared to a project and then from the project to the organization names the
    project copy, not the original, so one pass removes only the first generation and the
    personal statement would outlive its erasure in the second. Each pass handles the
    claims that name what the last one removed, until a pass removes nothing.

    A copy that two people shared independently names both. It is deleted only when none
    of its sources survives; otherwise the erased ones are struck from its list and it
    stays, because the other person's share is theirs to keep.
    """
    removed = 0
    gone = set(ids)
    frontier = ids
    while frontier:
        query = select(MemoryClaim).where(MemoryClaim.derived_from.has_any(_texts(frontier)))
        if organization_id is not None:
            query = query.where(MemoryClaim.organization_id == organization_id)
        rows = (await db.execute(query)).scalars().all()
        frontier = []
        for row in rows:
            remaining = [item for item in row.derived_from if item not in gone]
            if remaining:
                row.derived_from = remaining
                db.add(row)
                continue
            frontier.append(str(row.id))
            gone.add(str(row.id))
            await db.delete(row)
            removed += 1
        await db.flush()
    return removed


async def delete_for_scope(db: AsyncSession, *, organization_id: UUID, scope_key: str) -> int:
    """Erase one scope's claims, and the copies shared out of it, in one organization."""
    own = (
        (
            await db.execute(
                select(MemoryClaim.id).where(
                    MemoryClaim.organization_id == organization_id,
                    MemoryClaim.scope_key == scope_key,
                )
            )
        )
        .scalars()
        .all()
    )
    copies = await _delete_descendants(
        db, [str(identifier) for identifier in own], organization_id=organization_id
    )
    result = await db.execute(
        sa_delete(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id, MemoryClaim.scope_key == scope_key
        )
    )
    await db.execute(
        sa_delete(MemoryScopeState).where(
            MemoryScopeState.organization_id == organization_id,
            MemoryScopeState.scope_key == scope_key,
        )
    )
    await db.flush()
    if own:
        await prune_empty_objects(db, organization_id=organization_id)
    return (result.rowcount or 0) + copies  # ty: ignore[missing-attribute]


async def delete_everywhere_about(db: AsyncSession, *, scope_key: str) -> int:
    """Erase one owner's claims in every organization, and what was copied from them.

    For an account being deleted: the person's own scope, the shared copies whose
    ancestry is only their claims (`derived_from` names nothing else), and the
    change counters. A shared copy is derived data; it does not outlive its source.
    """
    own = (
        await db.execute(
            select(MemoryClaim.id, MemoryClaim.organization_id).where(
                MemoryClaim.scope_key == scope_key
            )
        )
    ).all()
    removed = await _delete_descendants(db, [str(row.id) for row in own])
    own_removed = await db.execute(sa_delete(MemoryClaim).where(MemoryClaim.scope_key == scope_key))
    removed += own_removed.rowcount or 0  # ty: ignore[missing-attribute]
    await db.execute(sa_delete(MemoryScopeState).where(MemoryScopeState.scope_key == scope_key))
    await db.flush()
    for organization_id in {row.organization_id for row in own}:
        await prune_empty_objects(db, organization_id=organization_id)
    return removed


async def delete_for_agent(db: AsyncSession, *, organization_id: UUID, agent_id: UUID) -> int:
    """Erase what one agent holds, and every copy shared out of it however far.

    A claim of the agent's that was shared to a project or the organization lives on there
    with no agent of its own, naming its source in `derived_from`; deleting only the agent's
    rows would report the agent cleared while the shared copy stayed readable.
    """
    own = (
        (
            await db.execute(
                select(MemoryClaim.id).where(
                    MemoryClaim.organization_id == organization_id,
                    MemoryClaim.agent_id == agent_id,
                )
            )
        )
        .scalars()
        .all()
    )
    copies = await _delete_descendants(
        db, [str(identifier) for identifier in own], organization_id=organization_id
    )
    result = await db.execute(
        sa_delete(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id, MemoryClaim.agent_id == agent_id
        )
    )
    await db.flush()
    if own:
        await prune_empty_objects(db, organization_id=organization_id)
    return (result.rowcount or 0) + copies  # ty: ignore[missing-attribute]


async def ancestry_scope_keys(
    db: AsyncSession, *, organization_id: UUID, claim_id: UUID
) -> set[str]:
    """Find every source audience without exposing ancestor contents to a caller."""
    seen: set[UUID] = set()
    frontier = [claim_id]
    keys: set[str] = set()
    while frontier:
        rows = (
            await db.execute(
                select(MemoryClaim.scope_key, MemoryClaim.derived_from).where(
                    MemoryClaim.organization_id == organization_id, MemoryClaim.id.in_(frontier)
                )
            )
        ).all()
        seen.update(frontier)
        keys.update(row.scope_key for row in rows)
        frontier = sorted({UUID(str(parent)) for row in rows for parent in row.derived_from} - seen)
    return keys


async def publish_note(
    db: AsyncSession,
    *,
    organization_id: UUID,
    source_id: UUID,
    scope_key: str,
    name: str,
    content: str,
) -> SharedMemoryNote:
    inserted = pg_insert(SharedMemoryNote).values(
        organization_id=organization_id,
        source_id=source_id,
        scope_key=scope_key,
        name=name,
        content=content,
    )
    result = await db.scalars(
        inserted.on_conflict_do_update(
            constraint="uq_shared_memory_note_source",
            set_={
                "name": inserted.excluded.name,
                "content": inserted.excluded.content,
                "updated_at": func.now(),
            },
        ).returning(SharedMemoryNote)
    )
    return result.one()


async def shared_notes(
    db: AsyncSession,
    *,
    organization_id: UUID,
    keys: Sequence[str],
    cursor: UUID | None,
    limit: int,
) -> list[SharedMemoryNote]:
    result = await db.scalars(
        select(SharedMemoryNote)
        .where(
            SharedMemoryNote.organization_id == organization_id,
            SharedMemoryNote.scope_key.in_(keys),
            SharedMemoryNote.id > cursor if cursor else true(),
        )
        .order_by(SharedMemoryNote.id)
        .limit(limit)
    )
    return list(result)


async def mail_source(
    db: AsyncSession, organization_id: UUID, *, lock: bool = False
) -> MemoryMailSource | None:
    query = select(MemoryMailSource).where(MemoryMailSource.organization_id == organization_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def mail_event(
    db: AsyncSession, *, organization_id: UUID, event_id: UUID
) -> MemoryMailEvent | None:
    return await db.scalar(
        select(MemoryMailEvent)
        .where(
            MemoryMailEvent.organization_id == organization_id,
            MemoryMailEvent.id == event_id,
        )
        .execution_options(populate_existing=True)
    )


async def admit_mail(
    db: AsyncSession,
    *,
    source: MemoryMailSource,
    grant_id: UUID,
    delivery_id: str,
    received_at: datetime,
    deadline: datetime | None,
    quote: str,
) -> UUID | None:
    return await db.scalar(
        pg_insert(MemoryMailEvent)
        .values(
            organization_id=source.organization_id,
            grant_id=grant_id,
            generation=source.generation,
            delivery_id=delivery_id,
            received_at=received_at,
            deadline=deadline,
            quote=quote,
            state="queued",
        )
        .on_conflict_do_nothing(constraint="uq_memory_mail_events_delivery")
        .returning(MemoryMailEvent.id)
    )


async def mail_seen(
    db: AsyncSession,
    *,
    organization_id: UUID,
    grant_id: UUID,
    delivery_id: str,
) -> bool:
    return (
        await db.scalar(
            select(MemoryMailEvent.id).where(
                MemoryMailEvent.organization_id == organization_id,
                MemoryMailEvent.grant_id == grant_id,
                MemoryMailEvent.delivery_id == delivery_id,
            )
        )
        is not None
    )


async def mail_events_since(db: AsyncSession, *, organization_id: UUID, since: datetime) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(MemoryMailEvent)
            .where(
                MemoryMailEvent.organization_id == organization_id,
                MemoryMailEvent.admitted_at >= since,
            )
        )
        or 0
    )


async def remove_mail_source(db: AsyncSession, source: MemoryMailSource) -> None:
    """Remove derived mail records and their non-delivered or decided Inbox entries."""
    await db.execute(
        sa_delete(Suggestion).where(
            Suggestion.organization_id == source.organization_id,
            Suggestion.payload["memory_mail"].as_boolean().is_(True),
        )
    )
    await db.delete(source)
    await db.flush()
    await prune_empty_objects(db, organization_id=source.organization_id)


async def prune_empty_objects(
    db: AsyncSession, *, organization_id: UUID, scope_key: str | None = None
) -> None:
    await db.execute(
        sa_delete(MemoryObject).where(
            MemoryObject.organization_id == organization_id,
            MemoryObject.scope_key == scope_key if scope_key is not None else true(),
            ~select(MemoryClaim.id).where(MemoryClaim.object_id == MemoryObject.id).exists(),
        )
    )


async def add_message_evidence(
    db: AsyncSession,
    *,
    claim_id: UUID,
    message_id: UUID,
    quote: str,
    occurred_at: datetime,
) -> None:
    await db.execute(
        pg_insert(MemoryClaimEvidence)
        .values(
            claim_id=claim_id,
            message_id=message_id,
            quote=quote,
            occurred_at=occurred_at,
        )
        .on_conflict_do_nothing()
    )


async def message_evidence(db: AsyncSession, claim_id: UUID) -> list[MemoryClaimEvidence]:
    return list(
        await db.scalars(
            select(MemoryClaimEvidence)
            .where(MemoryClaimEvidence.claim_id == claim_id)
            .order_by(MemoryClaimEvidence.occurred_at.desc(), MemoryClaimEvidence.message_id)
            .limit(10)
        )
    )
