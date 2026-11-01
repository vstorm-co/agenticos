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

from sqlalchemy import ARRAY, Text, and_, func, literal, or_, select, true
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.memory_claim import MemoryClaim, MemoryScopeState


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
    now = func.now()
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


async def get(db: AsyncSession, *, organization_id: UUID, claim_id: UUID) -> MemoryClaim | None:
    result = await db.execute(
        select(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id, MemoryClaim.id == claim_id
        )
    )
    return result.scalar_one_or_none()


async def many(
    db: AsyncSession, *, organization_id: UUID, claim_ids: Sequence[UUID]
) -> list[MemoryClaim]:
    if not claim_ids:
        return []
    result = await db.execute(
        select(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id, MemoryClaim.id.in_(list(claim_ids))
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
    scope_key: str,
    statuses: Sequence[str],
    skip: int,
    limit: int,
) -> tuple[list[MemoryClaim], int]:
    """Every claim one owner holds in an organization, under any agent, and the total."""
    clause = (
        MemoryClaim.organization_id == organization_id,
        MemoryClaim.scope_key == scope_key,
        MemoryClaim.status.in_(list(statuses)),
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
) -> list[MemoryClaim]:
    """The live claims on one topic in one scope, oldest first."""
    result = await db.execute(
        select(MemoryClaim)
        .where(
            MemoryClaim.organization_id == organization_id,
            _in_scopes([scope]),
            MemoryClaim.subject == subject,
            MemoryClaim.status.in_(list(statuses)),
        )
        .order_by(MemoryClaim.observed_at.asc(), MemoryClaim.id.asc())
    )
    return list(result.scalars().all())


async def without_subject(
    db: AsyncSession, *, organization_id: UUID, scope: ClaimScope
) -> list[MemoryClaim]:
    result = await db.execute(
        select(MemoryClaim).where(
            MemoryClaim.organization_id == organization_id,
            _in_scopes([scope]),
            MemoryClaim.subject.is_(None),
            MemoryClaim.status == "current",
        )
    )
    return list(result.scalars().all())


async def search(
    db: AsyncSession,
    *,
    organization_id: UUID,
    scopes: Sequence[ClaimScope],
    terms: Sequence[str],
    limit: int,
) -> list[MemoryClaim]:
    """Live claims whose statement or subject contains any term - no model call."""
    if not scopes or not terms:
        return []
    needles = [f"%{term}%" for term in terms]
    result = await db.execute(
        select(MemoryClaim)
        .where(
            MemoryClaim.organization_id == organization_id,
            _in_scopes(scopes),
            MemoryClaim.status.in_(["current", "disputed"]),
            _in_effect(),
            or_(
                *(MemoryClaim.statement.ilike(needle) for needle in needles),
                *(MemoryClaim.subject.ilike(needle) for needle in needles),
            ),
        )
        .order_by(MemoryClaim.observed_at.desc())
        .limit(limit * 4)
    )
    return list(result.scalars().all())


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
    return claim


async def set_status(
    db: AsyncSession, claim: MemoryClaim, status: str, *, effective_to: datetime | None = None
) -> None:
    claim.status = status
    if effective_to is not None:
        claim.effective_to = effective_to
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
    return (result.rowcount or 0) + copies  # ty: ignore[unresolved-attribute]


async def delete_everywhere_about(db: AsyncSession, *, scope_key: str) -> int:
    """Erase one owner's claims in every organization, and what was copied from them.

    For an account being deleted: the person's own scope, the shared copies whose
    ancestry is only their claims (`derived_from` names nothing else), and the
    change counters. A shared copy is derived data; it does not outlive its source.
    """
    own = (
        (await db.execute(select(MemoryClaim.id).where(MemoryClaim.scope_key == scope_key)))
        .scalars()
        .all()
    )
    removed = await _delete_descendants(db, [str(identifier) for identifier in own])
    own_removed = await db.execute(sa_delete(MemoryClaim).where(MemoryClaim.scope_key == scope_key))
    removed += own_removed.rowcount or 0  # ty: ignore[unresolved-attribute]
    await db.execute(sa_delete(MemoryScopeState).where(MemoryScopeState.scope_key == scope_key))
    await db.flush()
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
    return (result.rowcount or 0) + copies  # ty: ignore[unresolved-attribute]
