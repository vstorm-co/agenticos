"""Organization API key repository (PostgreSQL async)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_key import ApiKey
from app.db.models.user import User


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    name: str,
    prefix: str,
    key_hash: str,
    scopes: list[str],
    expires_at: datetime | None,
    oauth_grant_id: UUID | None = None,
) -> ApiKey:
    key = ApiKey(
        organization_id=organization_id,
        user_id=user_id,
        name=name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=scopes,
        expires_at=expires_at,
        oauth_grant_id=oauth_grant_id,
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)
    return key


async def get_by_prefix(db: AsyncSession, prefix: str) -> ApiKey | None:
    result = await db.execute(select(ApiKey).where(ApiKey.prefix == prefix))
    return result.scalar_one_or_none()


async def get(db: AsyncSession, key_id: UUID, *, organization_id: UUID) -> ApiKey | None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def list_for_organization(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID | None
) -> list[tuple[ApiKey, str]]:
    """Each key a person issued, with their email, newest first; one issuer's when
    `user_id` is set. OAuth access tokens are left out - they are listed as their
    grant, under connected applications."""
    query = (
        select(ApiKey, User.email)
        .join(User, User.id == ApiKey.user_id)
        .where(ApiKey.organization_id == organization_id, ApiKey.oauth_grant_id.is_(None))
        .order_by(ApiKey.created_at.desc())
    )
    if user_id is not None:
        query = query.where(ApiKey.user_id == user_id)
    result = await db.execute(query)
    return [(key, email) for key, email in result.all()]


async def update(db: AsyncSession, *, key: ApiKey, update_data: dict[str, Any]) -> ApiKey:
    for field, value in update_data.items():
        setattr(key, field, value)
    await db.flush()
    await db.refresh(key)
    return key


async def touch(db: AsyncSession, key_id: UUID, *, at: datetime, stale_before: datetime) -> None:
    """Record a use, at most once per window - a write per request is not worth it."""
    await db.execute(
        sql_update(ApiKey)
        .where(
            ApiKey.id == key_id,
            (ApiKey.last_used_at.is_(None)) | (ApiKey.last_used_at < stale_before),
        )
        .values(last_used_at=at)
    )
