"""Tenant/owner-scoped registration intent and compare-and-swap callback claims."""

from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chatgpt_registration import ChatGPTRegistration


async def start(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, host_id: UUID
) -> ChatGPTRegistration:
    statement = insert(ChatGPTRegistration).values(
        organization_id=organization_id, user_id=user_id, host_id=host_id, generation=uuid4()
    )
    statement = (
        statement.on_conflict_do_update(
            index_elements=["organization_id", "user_id"],
            set_={"generation": statement.excluded.generation},
        )
        .returning(ChatGPTRegistration)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(statement)).scalar_one()


async def get(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, locked: bool = False
) -> ChatGPTRegistration | None:
    statement = (
        select(ChatGPTRegistration)
        .where(
            ChatGPTRegistration.organization_id == organization_id,
            ChatGPTRegistration.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if locked:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def claim_client(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, generation: UUID, client_id: str
) -> bool:
    statement = (
        update(ChatGPTRegistration)
        .where(
            ChatGPTRegistration.organization_id == organization_id,
            ChatGPTRegistration.user_id == user_id,
            ChatGPTRegistration.generation == generation,
            (
                ChatGPTRegistration.client_id.is_(None)
                | (ChatGPTRegistration.client_id == client_id)
            ),
        )
        .values(client_id=client_id)
        .returning(ChatGPTRegistration.user_id)
    )
    return await db.scalar(statement) is not None
