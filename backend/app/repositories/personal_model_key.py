"""Personal model credentials are always queried by both tenant and owner."""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.personal_model_key import PersonalModelKey


async def get(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, provider: str, endpoint: str
) -> PersonalModelKey | None:
    return await db.scalar(
        select(PersonalModelKey)
        .execution_options(populate_existing=True)
        .where(
            PersonalModelKey.organization_id == organization_id,
            PersonalModelKey.user_id == user_id,
            PersonalModelKey.provider == provider,
            PersonalModelKey.endpoint == endpoint,
        )
    )


async def list_for(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> list[PersonalModelKey]:
    rows = await db.scalars(
        select(PersonalModelKey)
        .where(
            PersonalModelKey.organization_id == organization_id, PersonalModelKey.user_id == user_id
        )
        .order_by(PersonalModelKey.provider, PersonalModelKey.endpoint)
    )
    return list(rows)


async def save(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    provider: str,
    endpoint: str,
    sealed_secret: str,
    key_version: int,
) -> None:
    statement = insert(PersonalModelKey).values(
        id=uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        provider=provider,
        endpoint=endpoint,
        sealed_secret=sealed_secret,
        key_version=key_version,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["organization_id", "user_id", "provider", "endpoint"],
            set_={
                "sealed_secret": sealed_secret,
                "key_version": key_version,
                "updated_at": func.clock_timestamp(),
            },
        )
    )
    await db.flush()


async def delete(db: AsyncSession, *, organization_id: UUID, user_id: UUID, key_id: UUID) -> bool:
    row = await db.scalar(
        select(PersonalModelKey)
        .execution_options(populate_existing=True)
        .where(
            PersonalModelKey.id == key_id,
            PersonalModelKey.organization_id == organization_id,
            PersonalModelKey.user_id == user_id,
        )
    )
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True
