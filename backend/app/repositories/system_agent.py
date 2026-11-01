"""System-agent profiles (PostgreSQL async): one row per organization and role (#2575)."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system_agent_profile import SystemAgentProfile


async def get(db: AsyncSession, *, organization_id: UUID, role: str) -> SystemAgentProfile | None:
    result = await db.execute(
        select(SystemAgentProfile).where(
            SystemAgentProfile.organization_id == organization_id,
            SystemAgentProfile.role == role,
        )
    )
    return result.scalar_one_or_none()


async def provision(db: AsyncSession, *, organization_id: UUID, role: str) -> SystemAgentProfile:
    """The profile for a role, created disabled-by-nothing on first use.

    Created enabled but with no model: a role runs only once somebody has chosen
    what it runs on, so provisioning spends nothing. Safe to race - the insert is
    a no-op when another request provisioned it first.
    """
    await db.execute(
        pg_insert(SystemAgentProfile)
        .values(organization_id=organization_id, role=role, enabled=True)
        .on_conflict_do_nothing(index_elements=["organization_id", "role"])
    )
    profile = await get(db, organization_id=organization_id, role=role)
    assert profile is not None, "provisioning leaves a row behind"
    await db.refresh(profile)
    return profile


async def update(
    db: AsyncSession,
    profile: SystemAgentProfile,
    *,
    enabled: bool,
    model_profile_id: UUID | None,
    monthly_budget_usd: Decimal | None,
) -> SystemAgentProfile:
    profile.enabled = enabled
    profile.model_profile_id = model_profile_id
    profile.monthly_budget_usd = monthly_budget_usd
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile
