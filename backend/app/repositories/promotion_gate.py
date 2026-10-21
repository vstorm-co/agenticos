"""The eval suites guarding environments, and the promotions made past them."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_environment import AgentEnvironment
from app.db.models.eval_suite import EvalSuite
from app.db.models.promotion_gate import EnvironmentGuard, PromotionOverride


async def guards_for(
    db: AsyncSession, environment_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, list[UUID]]:
    """Each of these environments' guarding suites, oldest guard first."""
    if not environment_ids:
        return {}
    result = await db.execute(
        select(EnvironmentGuard)
        .where(
            EnvironmentGuard.environment_id.in_(environment_ids),
            EnvironmentGuard.organization_id == organization_id,
        )
        .order_by(EnvironmentGuard.created_at, EnvironmentGuard.suite_id)
    )
    guards: dict[UUID, list[UUID]] = {}
    for guard in result.scalars().all():
        guards.setdefault(guard.environment_id, []).append(guard.suite_id)
    return guards


async def replace_guards(
    db: AsyncSession, environment_id: UUID, suite_ids: Sequence[UUID], *, organization_id: UUID
) -> None:
    await db.execute(
        delete(EnvironmentGuard).where(
            EnvironmentGuard.environment_id == environment_id,
            EnvironmentGuard.organization_id == organization_id,
        )
    )
    db.add_all(
        EnvironmentGuard(
            environment_id=environment_id, suite_id=suite_id, organization_id=organization_id
        )
        for suite_id in suite_ids
    )
    await db.flush()


async def guarded_by(
    db: AsyncSession, suite_id: UUID, *, organization_id: UUID
) -> list[AgentEnvironment]:
    """The environments this suite guards, by name."""
    result = await db.execute(
        select(AgentEnvironment)
        .join(EnvironmentGuard, EnvironmentGuard.environment_id == AgentEnvironment.id)
        .where(
            EnvironmentGuard.suite_id == suite_id,
            EnvironmentGuard.organization_id == organization_id,
        )
        .order_by(AgentEnvironment.name)
    )
    return list(result.scalars().all())


async def guarded_by_dataset(
    db: AsyncSession, dataset_id: UUID, *, organization_id: UUID
) -> list[AgentEnvironment]:
    """The environments guarded by a suite that checks this dataset, by name."""
    result = await db.execute(
        select(AgentEnvironment)
        .join(EnvironmentGuard, EnvironmentGuard.environment_id == AgentEnvironment.id)
        .join(EvalSuite, EvalSuite.id == EnvironmentGuard.suite_id)
        .where(
            EvalSuite.dataset_id == dataset_id,
            EnvironmentGuard.organization_id == organization_id,
        )
        .order_by(AgentEnvironment.name)
        .distinct()
    )
    return list(result.scalars().all())


async def guarded_following_latest(
    db: AsyncSession, agent_id: UUID, *, organization_id: UUID
) -> list[AgentEnvironment]:
    """This agent's environments that follow publishes and name at least one guard."""
    result = await db.execute(
        select(AgentEnvironment)
        .where(
            AgentEnvironment.agent_id == agent_id,
            AgentEnvironment.organization_id == organization_id,
            AgentEnvironment.tracks_latest.is_(True),
            AgentEnvironment.id.in_(select(EnvironmentGuard.environment_id)),
        )
        .order_by(AgentEnvironment.name)
    )
    return list(result.scalars().all())


async def add_override(
    db: AsyncSession, *, organization_id: UUID, values: dict[str, Any]
) -> PromotionOverride:
    override = PromotionOverride(organization_id=organization_id, **values)
    db.add(override)
    await db.flush()
    await db.refresh(override)
    return override


async def overrides_for_versions(
    db: AsyncSession, version_ids: Sequence[UUID], *, organization_id: UUID
) -> dict[UUID, list[PromotionOverride]]:
    """The overrides made on each of these versions, oldest first."""
    if not version_ids:
        return {}
    result = await db.execute(
        select(PromotionOverride)
        .where(
            PromotionOverride.version_id.in_(version_ids),
            PromotionOverride.organization_id == organization_id,
        )
        .order_by(PromotionOverride.created_at)
    )
    overrides: dict[UUID, list[PromotionOverride]] = {}
    for override in result.scalars().all():
        overrides.setdefault(override.version_id, []).append(override)
    return overrides
