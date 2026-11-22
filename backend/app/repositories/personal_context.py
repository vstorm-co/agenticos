"""Tenant/person-scoped, rebuildable checkpoints; no application policy lives here."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import CHANNEL_SURFACES, AgentRun, RunSurface
from app.db.models.conversation import Message
from app.db.models.personal_context import PersonalContextCache

_INTERACTIVE_SURFACES = sorted({RunSurface.WEB, *CHANNEL_SURFACES})


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

    from app.db.models.channel_identity import ChannelIdentity
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
                ChannelIdentity.user_id,
                ChannelIdentity.is_active,
                ChannelIdentity.authorization_generation,
                Message.guardrail_refused,
                AgentRun.status,
                AgentRun.is_test,
                AgentRun.surface,
                AgentRun.user_id,
                AgentRun.key_scopes,
                AgentRun.parent_run_id,
                AgentRun.initiated_by_publisher_fallback,
                AgentRun.started_at,
                AgentRun.input_tokens,
                AgentRun.agent_version_id,
                AgentRun.test_spec,
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
        .outerjoin(ChannelIdentity, ChannelIdentity.id == Message.channel_identity_id)
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
                ToolCall.mcp_connection_id,
                ToolCall.started_at,
                ToolCall.completed_at,
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
    from sqlalchemy import and_
    from sqlalchemy.orm import selectinload

    from app.db.models.agent_run import AgentRun, RunStatus
    from app.db.models.conversation import Conversation, Message, ToolCall
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
            or_(
                Message.created_at >= since,
                select(ToolCall.id)
                .where(
                    ToolCall.message_id == Message.id,
                    ToolCall.tool_id == "ask_user_question",
                    ToolCall.completed_at >= since,
                    ToolCall.status == "completed",
                )
                .exists(),
            ),
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
                & or_(AgentRun.key_scopes.is_(None), AgentRun.key_scopes == JSONB.NULL)
                & AgentRun.initiated_by_publisher_fallback.is_(False)
                & AgentRun.parent_run_id.is_(None)
                & AgentRun.surface.in_(_INTERACTIVE_SURFACES),
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

    from app.db.models.agent_run import AgentRun
    from app.db.models.conversation import Message, ToolCall

    scope = (
        AgentRun.organization_id == organization_id,
        AgentRun.user_id == user_id,
        AgentRun.is_test.is_(False),
        AgentRun.parent_run_id.is_(None),
        AgentRun.surface.in_(_INTERACTIVE_SURFACES),
        or_(AgentRun.key_scopes.is_(None), AgentRun.key_scopes == JSONB.NULL),
        AgentRun.initiated_by_publisher_fallback.is_(False),
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


async def lock_delivery_sources(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, conversation_ids: Collection[UUID]
) -> None:
    """Hold existing DB access and cited source rows through checkpoint/delivery commit.

    Shared row locks block grant revocation, subject unlinking and source edits.
    New grants need no fence: they can only add access. External channel membership
    still uses ConversationService's existing live/cache confirmation contract.
    """
    from app.db.models.channel_identity import ChannelIdentity
    from app.db.models.conversation import Conversation, ToolCall
    from app.db.models.conversation_share import ConversationShare
    from app.db.models.group import GroupMember
    from app.db.models.organization import Organization, OrganizationMember
    from app.db.models.project import Project
    from app.db.models.resource_grant import ResourceGrant
    from app.db.models.user import User

    conversations = select(Conversation.id).where(
        Conversation.organization_id == organization_id, Conversation.id.in_(conversation_ids)
    )
    project_ids = select(Conversation.project_id).where(Conversation.id.in_(conversations))
    group_ids = select(GroupMember.group_id).where(GroupMember.user_id == user_id)
    messages = select(Message.id).where(Message.conversation_id.in_(conversations))
    for statement in (
        select(Organization.id).where(Organization.id == organization_id),
        select(User.id).where(User.id == user_id),
        select(OrganizationMember.user_id).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        ),
        select(GroupMember.id).where(GroupMember.user_id == user_id),
        select(ResourceGrant.id).where(
            ResourceGrant.organization_id == organization_id,
            or_(
                ResourceGrant.subject_user_id == user_id,
                ResourceGrant.subject_group_id.in_(group_ids),
            ),
        ),
        select(Project.id).where(
            Project.organization_id == organization_id, Project.id.in_(project_ids)
        ),
        conversations,
        select(ConversationShare.id).where(
            ConversationShare.conversation_id.in_(conversations),
            ConversationShare.shared_with == user_id,
        ),
        select(ChannelIdentity.id).where(
            or_(
                ChannelIdentity.user_id == user_id,
                ChannelIdentity.id.in_(
                    select(Message.channel_identity_id).where(Message.id.in_(messages))
                ),
            )
        ),
        messages,
        select(ToolCall.id).where(ToolCall.message_id.in_(messages)),
        select(AgentRun.id).where(
            AgentRun.organization_id == organization_id, AgentRun.conversation_id.in_(conversations)
        ),
    ):
        await db.execute(
            statement.order_by(statement.selected_columns[0]).with_for_update(read=True)
        )
