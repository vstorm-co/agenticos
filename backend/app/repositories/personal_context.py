"""Tenant/person-scoped, rebuildable checkpoints; no application policy lives here."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Message
from app.db.models.personal_context import PersonalContextCache


async def load(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> dict[str, dict[str, object]]:
    rows = await db.scalars(
        select(PersonalContextCache).where(
            PersonalContextCache.organization_id == organization_id,
            PersonalContextCache.user_id == user_id,
        )
    )
    return {row.source_key: row.payload for row in rows}


async def save(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, key: str, payload: dict[str, object]
) -> None:
    statement = insert(PersonalContextCache).values(
        organization_id=organization_id,
        user_id=user_id,
        source_key=key,
        payload=payload,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["organization_id", "user_id", "source_key"],
            set_={"payload": statement.excluded.payload, "updated_at": func.now()},
        )
    )
    await db.flush()


async def retain(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, keys: Collection[str]
) -> None:
    """Drop checkpoints whose sources changed or are no longer authorized."""
    await db.execute(
        delete(PersonalContextCache).where(
            PersonalContextCache.organization_id == organization_id,
            PersonalContextCache.user_id == user_id,
            PersonalContextCache.source_key.not_in(keys),
        )
    )
    await db.flush()


async def erase(db: AsyncSession, *, organization_id: UUID, user_id: UUID) -> None:
    await retain(db, organization_id=organization_id, user_id=user_id, keys=[])


async def conversation_revision(
    db: AsyncSession, *, organization_id: UUID, conversation_id: UUID
) -> str:
    """Hash source rows in PostgreSQL, without transferring unchanged transcript text."""
    from sqlalchemy import Text, cast, func, literal
    from sqlalchemy.dialects.postgresql import aggregate_order_by

    from app.db.models.conversation import Conversation, ToolCall

    def hashed(value: ColumnElement[str]) -> ColumnElement[str]:
        return func.encode(func.sha256(func.convert_to(value, "UTF8")), "hex")

    turn_hash = hashed(
        cast(
            func.jsonb_build_array(
                Message.id,
                Message.role,
                Message.content,
                Message.author_user_id,
                Message.guardrail_refused,
                AgentRun.status,
                AgentRun.is_test,
            ),
            Text,
        )
    )
    turns = (
        select(
            hashed(
                func.coalesce(
                    func.string_agg(turn_hash, aggregate_order_by(literal("|"), Message.ordinal)),
                    "",
                )
            )
        )
        .select_from(Message)
        .outerjoin(
            AgentRun,
            AgentRun.id == Message.run_id,
        )
        .where(Message.conversation_id == conversation_id)
        .scalar_subquery()
    )
    tool_hash = hashed(
        cast(
            func.jsonb_build_array(
                ToolCall.id,
                ToolCall.status,
                ToolCall.tool_id,
                ToolCall.presentation_kind,
                ToolCall.args,
                ToolCall.result,
            ),
            Text,
        )
    )
    tools = (
        select(
            hashed(
                func.coalesce(
                    func.string_agg(tool_hash, aggregate_order_by(literal("|"), ToolCall.id)), ""
                )
            )
        )
        .select_from(ToolCall)
        .join(
            Message,
            Message.id == ToolCall.message_id,
        )
        .where(Message.conversation_id == conversation_id)
        .scalar_subquery()
    )
    revision = await db.scalar(
        select(
            hashed(
                cast(
                    func.jsonb_build_array(
                        turns,
                        tools,
                        Conversation.guardrail_revision,
                        Conversation.user_id,
                        Conversation.project_id,
                    ),
                    Text,
                )
            )
        ).where(
            Conversation.id == conversation_id,
            Conversation.organization_id == organization_id,
        )
    )
    return revision or "missing"


async def transcript_page(
    db: AsyncSession, *, organization_id: UUID, conversation_id: UUID, after: int, since: datetime
) -> list[tuple[Message, AgentRun | None]]:
    """Admitted text plus native identities, paged by immutable transcript ordinal."""
    from sqlalchemy import and_, or_
    from sqlalchemy.orm import selectinload

    from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
    from app.db.models.conversation import Conversation, Message
    from app.repositories.conversation import retained_prompt_admitted

    rows = await db.execute(
        select(Message, AgentRun)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(AgentRun, AgentRun.id == Message.run_id)
        .options(selectinload(Message.tool_calls))
        .where(
            Conversation.organization_id == organization_id,
            Message.conversation_id == conversation_id,
            Message.ordinal > after,
            Message.created_at >= since,
            Message.guardrail_refused.is_(False),
            Message.role.in_(["user", "assistant"]),
            or_(
                and_(
                    AgentRun.id.is_(None),
                    Message.run_id.is_(None),
                    or_(
                        and_(Message.role == "user", retained_prompt_admitted()),
                        and_(Message.role == "assistant", Message.model_name.is_not(None)),
                    ),
                ),
                (AgentRun.status != RunStatus.RUNNING.value)
                & AgentRun.is_test.is_(False)
                & AgentRun.initiated_by_publisher_fallback.is_(False)
                & AgentRun.parent_run_id.is_(None)
                & AgentRun.surface.not_in([RunSurface.EVAL.value, RunSurface.PROACTIVE.value]),
            ),
        )
        .order_by(Message.ordinal)
        .limit(100)
    )
    return list(rows.tuples().all())


async def for_user(db: AsyncSession, *, user_id: UUID) -> list[PersonalContextCache]:
    """Subject-scoped inventory for the person's export; service rechecks source access."""
    return list(
        (
            await db.scalars(
                select(PersonalContextCache).where(PersonalContextCache.user_id == user_id)
            )
        ).all()
    )


async def removed_resources(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> list[dict[str, object]]:
    return list(
        (
            await db.scalars(
                select(PersonalContextCache.payload)
                .where(
                    PersonalContextCache.organization_id == organization_id,
                    PersonalContextCache.user_id == user_id,
                    PersonalContextCache.source_key.startswith("removed-routine:", autoescape=True),
                )
                .order_by(PersonalContextCache.created_at.desc())
            )
        ).all()
    )


async def usage(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, time_zone: str
) -> dict[str, object]:
    """Observed retained activity is evidence of use, never proof of lifetime non-use."""
    from sqlalchemy import distinct, func

    from app.db.models.agent_run import AgentRun, RunSurface
    from app.db.models.conversation import Message, ToolCall

    scope = (
        AgentRun.organization_id == organization_id,
        AgentRun.user_id == user_id,
        AgentRun.is_test.is_(False),
        AgentRun.parent_run_id.is_(None),
        AgentRun.surface.not_in([RunSurface.EVAL.value, RunSurface.PROACTIVE.value]),
    )
    days = await db.scalar(
        select(
            func.count(distinct(func.date(func.timezone(time_zone, AgentRun.started_at))))
        ).where(*scope)
    )
    names = (
        await db.scalars(
            select(func.coalesce(ToolCall.tool_id, ToolCall.tool_name))
            .join(Message, Message.id == ToolCall.message_id)
            .join(AgentRun, AgentRun.id == Message.run_id)
            .where(
                *scope,
                ToolCall.presentation_kind.is_distinct_from("generic"),
                ToolCall.status == "completed",
            )
            .distinct()
            .order_by(func.coalesce(ToolCall.tool_id, ToolCall.tool_name))
            .limit(200)
        )
    ).all()
    return {
        "active_days": days or 0,
        "observed_tools": list(names),
        "coverage": "retained_non_test_runs_only",
    }
