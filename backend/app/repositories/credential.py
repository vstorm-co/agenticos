"""Credential and ModelProfile repositories (PostgreSQL async).

`organization_id` is a required keyword on every function here - a provider
key is the last thing that should leak across tenants, and a forgotten filter
must not look like an ordinary call (see tests/test_org_scope_regression.py).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.credential import ModelProfile


async def get_profile(
    db: AsyncSession, profile_id: UUID, *, organization_id: UUID
) -> ModelProfile | None:
    result = await db.execute(
        select(ModelProfile).where(
            ModelProfile.id == profile_id,
            ModelProfile.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_profile_by_label(
    db: AsyncSession, label: str, *, organization_id: UUID
) -> ModelProfile | None:
    result = await db.execute(
        select(ModelProfile).where(
            ModelProfile.label == label,
            ModelProfile.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_profiles_by_ids(
    db: AsyncSession, profile_ids: list[UUID], *, organization_id: UUID
) -> dict[UUID, ModelProfile]:
    """Fetch several profiles at once - used to resolve a fallback chain."""
    if not profile_ids:
        return {}
    result = await db.execute(
        select(ModelProfile).where(
            ModelProfile.id.in_(profile_ids),
            ModelProfile.organization_id == organization_id,
        )
    )
    return {profile.id: profile for profile in result.scalars().all()}


async def list_profiles(db: AsyncSession, *, organization_id: UUID) -> list[ModelProfile]:
    result = await db.execute(
        select(ModelProfile)
        .where(ModelProfile.organization_id == organization_id)
        .order_by(ModelProfile.label.asc())
    )
    return list(result.scalars().all())


async def create_profile(
    db: AsyncSession,
    *,
    organization_id: UUID,
    label: str,
    provider: str,
    model: str,
    secret_id: UUID | None,
    base_url: str | None = None,
    params: dict | None = None,
    allow_byo: bool = False,
    fallback_profile_ids: list[str] | None = None,
    context_length: int | None = None,
) -> ModelProfile:
    profile = ModelProfile(
        organization_id=organization_id,
        label=label,
        provider=provider,
        model=model,
        secret_id=secret_id,
        base_url=base_url,
        params=params or {},
        allow_byo=allow_byo,
        fallback_profile_ids=fallback_profile_ids or [],
        context_length=context_length,
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


async def delete_profile(db: AsyncSession, profile_id: UUID, *, organization_id: UUID) -> bool:
    profile = await get_profile(db, profile_id, organization_id=organization_id)
    if profile is None:
        return False
    await db.delete(profile)
    await db.flush()
    return True
