"""Owner-scoped rows and fenced drivers; lifecycle policy stays in the service."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.locks import LockScope, hold_name
from app.db.models.agent_run import AgentRun
from app.db.models.conversation_environment import (
    ConversationEnvironment,
    ConversationEnvironmentDriver,
)
from app.schemas.conversation_environment import (
    ConversationEnvironmentKind,
)


async def lock_owner(db: AsyncSession, organization_id: UUID, user_id: UUID) -> None:
    await hold_name(db, LockScope.CONVERSATION_ENVIRONMENT, f"{organization_id}/{user_id}")


async def latest(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
    kind: ConversationEnvironmentKind,
    for_update: bool = False,
) -> ConversationEnvironment | None:
    query = (
        select(ConversationEnvironment)
        .where(
            ConversationEnvironment.organization_id == organization_id,
            ConversationEnvironment.user_id == user_id,
            ConversationEnvironment.conversation_id == conversation_id,
            ConversationEnvironment.agent_id == agent_id,
            ConversationEnvironment.kind == kind,
        )
        .order_by(ConversationEnvironment.created_at.desc(), ConversationEnvironment.id.desc())
        .limit(1)
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query.execution_options(populate_existing=True))


async def owned(
    db: AsyncSession,
    identity: UUID,
    *,
    organization_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    for_update: bool = False,
) -> ConversationEnvironment | None:
    query = select(ConversationEnvironment).where(
        ConversationEnvironment.id == identity,
        ConversationEnvironment.organization_id == organization_id,
        ConversationEnvironment.user_id == user_id,
        ConversationEnvironment.conversation_id == conversation_id,
    )
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query.execution_options(populate_existing=True))


async def for_worker(
    db: AsyncSession,
    identity: UUID,
    *,
    for_update: bool = False,
) -> ConversationEnvironment | None:
    query = select(ConversationEnvironment).where(ConversationEnvironment.id == identity)
    if for_update:
        query = query.with_for_update()
    return await db.scalar(query.execution_options(populate_existing=True))


async def active_count(
    db: AsyncSession, organization_id: UUID, user_id: UUID, now: datetime
) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(ConversationEnvironment)
            .where(
                ConversationEnvironment.organization_id == organization_id,
                ConversationEnvironment.user_id == user_id,
                or_(
                    ConversationEnvironment.resource_ciphertext.is_not(None),
                    and_(
                        ConversationEnvironment.state.in_(("starting", "ready")),
                        ConversationEnvironment.expires_at > now,
                    ),
                ),
            )
        )
        or 0
    )


async def add(db: AsyncSession, row: ConversationEnvironment) -> ConversationEnvironment:
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def driver(db: AsyncSession, resource_key: str) -> ConversationEnvironmentDriver | None:
    return await db.scalar(
        select(ConversationEnvironmentDriver)
        .where(ConversationEnvironmentDriver.resource_key == resource_key)
        .execution_options(populate_existing=True)
    )


async def claim_driver(
    db: AsyncSession,
    resource_key: str,
    *,
    organization_id: UUID,
    user_id: UUID | None,
    token: UUID,
    control: Literal["human", "agent"],
    now: datetime,
    lease_until: datetime,
) -> bool:
    statement = (
        insert(ConversationEnvironmentDriver)
        .values(
            resource_key=resource_key,
            organization_id=organization_id,
            actor_user_id=user_id,
            control=control,
            lease_token=token,
            lease_until=lease_until,
        )
        .on_conflict_do_update(
            index_elements=[ConversationEnvironmentDriver.resource_key],
            set_={
                "organization_id": organization_id,
                "actor_user_id": user_id,
                "control": control,
                "lease_token": token,
                "lease_until": lease_until,
            },
            where=ConversationEnvironmentDriver.lease_until <= now,
        )
        .returning(ConversationEnvironmentDriver.resource_key)
    )
    return await db.scalar(statement) is not None


async def renew_driver(
    db: AsyncSession,
    resource_key: str,
    *,
    token: UUID,
    now: datetime,
    lease_until: datetime,
) -> bool:
    result = await db.scalar(
        update(ConversationEnvironmentDriver)
        .where(
            ConversationEnvironmentDriver.resource_key == resource_key,
            ConversationEnvironmentDriver.lease_token == token,
            ConversationEnvironmentDriver.lease_until > now,
        )
        .values(lease_until=lease_until)
        .returning(ConversationEnvironmentDriver.resource_key)
    )
    return result is not None


async def release_driver(db: AsyncSession, resource_key: str, *, token: UUID) -> None:
    await db.execute(
        delete(ConversationEnvironmentDriver).where(
            ConversationEnvironmentDriver.resource_key == resource_key,
            ConversationEnvironmentDriver.lease_token == token,
        )
    )


async def for_socket(
    db: AsyncSession, identity: UUID, *, user_id: UUID, conversation_id: UUID
) -> ConversationEnvironment | None:
    return await db.scalar(
        select(ConversationEnvironment)
        .where(
            ConversationEnvironment.id == identity,
            ConversationEnvironment.user_id == user_id,
            ConversationEnvironment.conversation_id == conversation_id,
            ConversationEnvironment.organization_id.is_not(None),
        )
        .execution_options(populate_existing=True)
    )


async def sweep_candidates(
    db: AsyncSession, now: datetime, *, limit: int = 100
) -> list[ConversationEnvironment]:
    return list(
        await db.scalars(
            select(ConversationEnvironment)
            .where(
                or_(
                    ConversationEnvironment.expires_at <= now,
                    and_(
                        or_(
                            ConversationEnvironment.session_lifetime == "run",
                            ConversationEnvironment.state == "starting",
                        ),
                        ConversationEnvironment.source_run_id.is_not(None),
                        exists(
                            select(AgentRun.id).where(
                                AgentRun.id == ConversationEnvironment.source_run_id,
                                AgentRun.status != "running",
                            )
                        ),
                    ),
                    ConversationEnvironment.organization_id.is_(None),
                    ConversationEnvironment.user_id.is_(None),
                    ConversationEnvironment.conversation_id.is_(None),
                    ConversationEnvironment.agent_id.is_(None),
                ),
                or_(
                    ConversationEnvironment.state.in_(("starting", "ready")),
                    ConversationEnvironment.resource_ciphertext.is_not(None),
                ),
            )
            .order_by(ConversationEnvironment.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )


async def active_for_maintenance(
    db: AsyncSession, now: datetime, *, limit: int = 100
) -> list[ConversationEnvironment]:
    return list(
        await db.scalars(
            select(ConversationEnvironment)
            .where(
                ConversationEnvironment.state == "ready",
                ConversationEnvironment.expires_at > now,
            )
            .order_by(ConversationEnvironment.last_maintained_at.asc().nulls_first())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
