"""Persistence for a workflow's log alert rules and the times they fired."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Interval, func, literal, or_, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_log_alert import WorkflowLogAlertFiring, WorkflowLogAlertRule


async def list_for_workflow(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID
) -> list[WorkflowLogAlertRule]:
    """One workflow's rules, oldest first."""
    result = await db.execute(
        select(WorkflowLogAlertRule)
        .where(
            WorkflowLogAlertRule.organization_id == organization_id,
            WorkflowLogAlertRule.workflow_id == workflow_id,
        )
        .order_by(WorkflowLogAlertRule.created_at, WorkflowLogAlertRule.id)
    )
    return list(result.scalars())


async def count_for_workflow(db: AsyncSession, *, organization_id: UUID, workflow_id: UUID) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                WorkflowLogAlertRule.organization_id == organization_id,
                WorkflowLogAlertRule.workflow_id == workflow_id,
            )
        )
        or 0
    )


async def get(
    db: AsyncSession, rule_id: UUID, *, organization_id: UUID, workflow_id: UUID
) -> WorkflowLogAlertRule | None:
    result = await db.execute(
        select(WorkflowLogAlertRule).where(
            WorkflowLogAlertRule.id == rule_id,
            WorkflowLogAlertRule.organization_id == organization_id,
            WorkflowLogAlertRule.workflow_id == workflow_id,
        )
    )
    return result.scalar_one_or_none()


async def get_for_update(db: AsyncSession, rule_id: UUID) -> WorkflowLogAlertRule | None:
    """The rule, row-locked: taken before judging whether it is due, so two overlapping
    evaluations cannot both fire it."""
    result = await db.execute(
        select(WorkflowLogAlertRule).where(WorkflowLogAlertRule.id == rule_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def list_due_ids(db: AsyncSession, *, now: datetime) -> list[UUID]:
    """Every enabled rule, in every organization, that never fired or last fired at least its
    window ago."""
    window = type_coerce(
        func.make_interval(0, 0, 0, 0, 0, WorkflowLogAlertRule.window_minutes), Interval
    )
    result = await db.execute(
        select(WorkflowLogAlertRule.id).where(
            WorkflowLogAlertRule.enabled.is_(True),
            or_(
                WorkflowLogAlertRule.last_fired_at.is_(None),
                WorkflowLogAlertRule.last_fired_at
                <= literal(now, DateTime(timezone=True)) - window,
            ),
        )
    )
    return list(result.scalars())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    name: str,
    outcomes: list[str],
    node_instance_id: UUID | None,
    message_contains: str | None,
    threshold: int,
    window_minutes: int,
    audience: list[str],
    user_ids: list[UUID],
    enabled: bool,
    created_by_user_id: UUID | None,
) -> WorkflowLogAlertRule:
    rule = WorkflowLogAlertRule(
        organization_id=organization_id,
        workflow_id=workflow_id,
        name=name,
        outcomes=outcomes,
        node_instance_id=node_instance_id,
        message_contains=message_contains,
        threshold=threshold,
        window_minutes=window_minutes,
        audience=audience,
        user_ids=user_ids,
        enabled=enabled,
        created_by_user_id=created_by_user_id,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return rule


async def update(
    db: AsyncSession, *, rule: WorkflowLogAlertRule, fields: dict[str, Any]
) -> WorkflowLogAlertRule:
    for name, value in fields.items():
        setattr(rule, name, value)
    await db.flush()
    await db.refresh(rule)
    return rule


async def delete(db: AsyncSession, rule: WorkflowLogAlertRule) -> None:
    await db.delete(rule)
    await db.flush()


async def create_firing(
    db: AsyncSession, *, rule_id: UUID, fired_at: datetime, count: int, window_start: datetime
) -> WorkflowLogAlertFiring:
    firing = WorkflowLogAlertFiring(
        rule_id=rule_id, fired_at=fired_at, count=count, window_start=window_start
    )
    db.add(firing)
    await db.flush()
    await db.refresh(firing)
    return firing


async def latest_firings(
    db: AsyncSession, rule_ids: list[UUID]
) -> dict[UUID, WorkflowLogAlertFiring]:
    """The newest firing of each of `rule_ids` that has fired."""
    if not rule_ids:
        return {}
    newest = (
        select(
            WorkflowLogAlertFiring.rule_id, func.max(WorkflowLogAlertFiring.fired_at).label("at")
        )
        .where(WorkflowLogAlertFiring.rule_id.in_(rule_ids))
        .group_by(WorkflowLogAlertFiring.rule_id)
        .subquery()
    )
    result = await db.execute(
        select(WorkflowLogAlertFiring).join(
            newest,
            (WorkflowLogAlertFiring.rule_id == newest.c.rule_id)
            & (WorkflowLogAlertFiring.fired_at == newest.c.at),
        )
    )
    return {firing.rule_id: firing for firing in result.scalars()}
