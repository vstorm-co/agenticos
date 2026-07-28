"""AgentEmbed repository - widgets, and the public key each is found by."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_embed import AgentEmbed


async def get_by_key(db: AsyncSession, public_key: str) -> AgentEmbed | None:
    """Find one widget by the key in its script tag.

    Deliberately **unscoped**, like `channel_bot.get_for_inbound`: the caller is
    a request from the public internet, which carries a key and nothing else.
    The tenant is read *off the row*, never taken from the request. Grep for
    this function when auditing cross-tenant reads.
    """
    result = await db.execute(select(AgentEmbed).where(AgentEmbed.public_key == public_key))
    return result.scalar_one_or_none()


async def get(db: AsyncSession, embed_id: UUID, *, organization_id: UUID) -> AgentEmbed | None:
    """One widget inside its organization - every authenticated read."""
    result = await db.execute(
        select(AgentEmbed).where(
            AgentEmbed.id == embed_id, AgentEmbed.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def list_for_agent(
    db: AsyncSession, *, agent_id: UUID, organization_id: UUID
) -> list[AgentEmbed]:
    """Every widget publishing one agent, oldest first."""
    result = await db.execute(
        select(AgentEmbed)
        .where(AgentEmbed.agent_id == agent_id, AgentEmbed.organization_id == organization_id)
        .order_by(AgentEmbed.created_at.asc())
    )
    return list(result.scalars().all())


async def count_for_org(db: AsyncSession, *, organization_id: UUID) -> int:
    result = await db.execute(
        select(func.count(AgentEmbed.id)).where(AgentEmbed.organization_id == organization_id)
    )
    return result.scalar() or 0


async def create(db: AsyncSession, *, embed: AgentEmbed) -> AgentEmbed:
    db.add(embed)
    await db.flush()
    await db.refresh(embed)
    return embed


async def update(
    db: AsyncSession, *, db_embed: AgentEmbed, update_data: dict[str, object]
) -> AgentEmbed:
    for field, value in update_data.items():
        setattr(db_embed, field, value)
    await db.flush()
    await db.refresh(db_embed)
    return db_embed


async def delete(db: AsyncSession, *, db_embed: AgentEmbed) -> None:
    await db.delete(db_embed)
    await db.flush()
