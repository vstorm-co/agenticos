"""Record each activation once; the locked routine owns ordering and bounded retention."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.routine_health import RoutineHealthObservation

RoutineKind = Literal["trigger", "watch"]
RETAINED_OBSERVATIONS = 50


def _parent(kind: RoutineKind, routine_id: UUID) -> ColumnElement[bool]:
    column = (
        RoutineHealthObservation.trigger_id
        if kind == "trigger"
        else RoutineHealthObservation.watch_id
    )
    return column == routine_id


async def observe(
    db: AsyncSession,
    *,
    kind: RoutineKind,
    routine_id: UUID,
    organization_id: UUID,
    user_id: UUID,
    activation_at: datetime,
    healthy: bool,
    reset_at: datetime | None,
) -> int:
    """The current failure streak in activation order, even when callbacks arrive out of order.

    The caller must lock the parent before inserting, counting or pruning. A parked
    run is not an observation. Replaying an activation cannot change its verdict.
    """
    await db.execute(
        insert(RoutineHealthObservation)
        .values(
            organization_id=organization_id,
            user_id=user_id,
            trigger_id=routine_id if kind == "trigger" else None,
            watch_id=routine_id if kind == "watch" else None,
            activation_at=activation_at,
            healthy=healthy,
        )
        .on_conflict_do_nothing()
    )
    parent = _parent(kind, routine_id)
    query = select(RoutineHealthObservation.healthy).where(
        parent,
        RoutineHealthObservation.organization_id == organization_id,
    )
    if reset_at is not None:
        query = query.where(RoutineHealthObservation.activation_at >= reset_at)
    results = await db.scalars(
        query.order_by(RoutineHealthObservation.activation_at.desc()).limit(20)
    )
    failures = 0
    for passed in results:
        if passed:
            break
        failures += 1
    retained = (
        select(RoutineHealthObservation.id)
        .where(parent)
        .order_by(
            RoutineHealthObservation.activation_at.desc(),
            RoutineHealthObservation.id.desc(),
        )
        .limit(RETAINED_OBSERVATIONS)
    )
    await db.execute(
        delete(RoutineHealthObservation).where(
            parent,
            RoutineHealthObservation.id.not_in(retained),
        )
    )
    return failures
