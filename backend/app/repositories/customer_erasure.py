"""The stores that hold something about one WhatsApp customer, for erasing them (#2076).

Every query filters by organization: a business-scoped id is only unique inside the
one organization whose bot it came from. Repositories flush; the caller commits.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import ReturningDelete, ReturningUpdate

from app.db.models.agent_run import AgentRun, ApprovalStatus, ToolApproval
from app.db.models.background_job import BackgroundJob
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_prompt import ChannelPrompt
from app.db.models.channel_session import ChannelSession
from app.db.models.conversation import Conversation, Message
from app.db.models.notification import Notification
from app.db.models.run_manifest import RunManifest
from app.db.models.whatsapp_customer import WhatsAppCustomer


async def _affected(
    db: AsyncSession, statement: ReturningDelete[Any] | ReturningUpdate[Any]
) -> int:
    """Run a DML statement that returns the ids of the rows it changed, and count them."""
    result = await db.execute(statement)
    await db.flush()
    return len(result.all())


async def whatsapp_bot_ids(db: AsyncSession, *, organization_id: UUID) -> list[UUID]:
    """Every WhatsApp bot of the organization, active or not."""
    result = await db.execute(
        select(ChannelBot.id).where(
            ChannelBot.organization_id == organization_id, ChannelBot.platform == "whatsapp"
        )
    )
    return list(result.scalars().all())


async def stranger_runs_of_identity(
    db: AsyncSession, *, organization_id: UUID, identity_id: UUID
) -> list[AgentRun]:
    """The runs this chat account started as somebody nobody could name.

    Only those: a run a member started during a period the account was linked is the
    member's, and is not read here.
    """
    result = await db.execute(
        select(AgentRun)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.channel_identity_id == identity_id,
            AgentRun.initiated_by_publisher_fallback.is_(True),
        )
        .order_by(AgentRun.id)
    )
    return list(result.scalars().all())


async def conversation_ids(
    db: AsyncSession, *, organization_id: UUID, identity_id: UUID
) -> list[UUID]:
    """The threads this chat account is in, kept only when no member owns them.

    Read through its sessions, its runs and the messages it wrote, so a thread a
    `/new` left behind is found too. A thread owned by a member, from a period the
    account was linked, is theirs and is left.
    """
    candidates = (
        select(ChannelSession.conversation_id)
        .join(ChannelBot, ChannelBot.id == ChannelSession.bot_id)
        .where(
            ChannelSession.identity_id == identity_id,
            ChannelBot.organization_id == organization_id,
            ChannelSession.conversation_id.is_not(None),
        )
        .union(
            select(AgentRun.conversation_id).where(
                AgentRun.organization_id == organization_id,
                AgentRun.channel_identity_id == identity_id,
                AgentRun.conversation_id.is_not(None),
            ),
            select(Message.conversation_id).where(Message.channel_identity_id == identity_id),
        )
    )
    result = await db.execute(
        select(Conversation.id).where(
            Conversation.organization_id == organization_id,
            Conversation.user_id.is_(None),
            Conversation.id.in_(candidates),
        )
    )
    return list(result.scalars().all())


async def conversations(
    db: AsyncSession, *, organization_id: UUID, ids: Collection[UUID]
) -> list[Conversation]:
    """The threads with these ids that belong to the organization."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.organization_id == organization_id, Conversation.id.in_(ids)
        )
    )
    return list(result.scalars().all())


async def delete_manifests(
    db: AsyncSession, *, organization_id: UUID, run_ids: Collection[UUID]
) -> int:
    """Drop what reached the model on these runs."""
    return await _affected(
        db,
        delete(RunManifest)
        .where(RunManifest.organization_id == organization_id, RunManifest.run_id.in_(run_ids))
        .returning(RunManifest.id),
    )


async def delete_prompts(
    db: AsyncSession,
    *,
    organization_id: UUID,
    bot_ids: Collection[UUID],
    platform_chat_id: str,
) -> int:
    """Drop the buttons and questions put to this chat on any of these bots."""
    return await _affected(
        db,
        delete(ChannelPrompt)
        .where(
            ChannelPrompt.organization_id == organization_id,
            ChannelPrompt.bot_id.in_(bot_ids),
            ChannelPrompt.platform_chat_id == platform_chat_id,
        )
        .returning(ChannelPrompt.id),
    )


async def delete_handback_jobs(
    db: AsyncSession, *, organization_id: UUID, concurrency_keys: Collection[str]
) -> tuple[int, int]:
    """Drop the answers queued for this chat, and say how many a worker holds right now.

    A job a worker is running is left: deleting its row would not stop the send, and
    the worker settles it. Returns `(deleted, left running)`.
    """
    running = await db.execute(
        select(BackgroundJob.id).where(
            BackgroundJob.organization_id == organization_id,
            BackgroundJob.concurrency_key.in_(concurrency_keys),
            BackgroundJob.status == "running",
        )
    )
    deleted = await _affected(
        db,
        delete(BackgroundJob)
        .where(
            BackgroundJob.organization_id == organization_id,
            BackgroundJob.concurrency_key.in_(concurrency_keys),
            BackgroundJob.status != "running",
        )
        .returning(BackgroundJob.id),
    )
    return deleted, len(running.scalars().all())


async def delete_notifications(
    db: AsyncSession,
    *,
    organization_id: UUID,
    event_type: str,
    occurrence_ids: Collection[str],
) -> int:
    """Drop the notifications of one event type that name these occurrences."""
    return await _affected(
        db,
        delete(Notification)
        .where(
            Notification.organization_id == organization_id,
            Notification.event_type == event_type,
            Notification.occurrence_id.in_(occurrence_ids),
        )
        .returning(Notification.id),
    )


async def approvals_of_runs(
    db: AsyncSession, *, organization_id: UUID, run_ids: Collection[UUID]
) -> list[ToolApproval]:
    """Every approval of these runs, decided or not."""
    result = await db.execute(
        select(ToolApproval).where(
            ToolApproval.organization_id == organization_id, ToolApproval.run_id.in_(run_ids)
        )
    )
    return list(result.scalars().all())


async def end_pending_approvals(
    db: AsyncSession, *, organization_id: UUID, run_ids: Collection[UUID], at: datetime
) -> int:
    """Expire the approvals of these runs that nobody has decided, with no decider."""
    return await _affected(
        db,
        update(ToolApproval)
        .where(
            ToolApproval.organization_id == organization_id,
            ToolApproval.run_id.in_(run_ids),
            ToolApproval.status == ApprovalStatus.PENDING.value,
        )
        .values(status=ApprovalStatus.EXPIRED.value, decided_at=at)
        .returning(ToolApproval.id),
    )


async def redact_approvals(
    db: AsyncSession, *, organization_id: UUID, run_ids: Collection[UUID]
) -> int:
    """Take the arguments, the names and the note out of every approval of these runs."""
    return await _affected(
        db,
        update(ToolApproval)
        .where(ToolApproval.organization_id == organization_id, ToolApproval.run_id.in_(run_ids))
        .values(tool_args={"redacted": True}, context=None, note=None)
        .returning(ToolApproval.id),
    )


async def delete_customers(
    db: AsyncSession, *, organization_id: UUID, bot_ids: Collection[UUID], bsuid: str
) -> int:
    """Drop the customer's records on these bots; their held runs go with them."""
    return await _affected(
        db,
        delete(WhatsAppCustomer)
        .where(
            WhatsAppCustomer.organization_id == organization_id,
            WhatsAppCustomer.bot_id.in_(bot_ids),
            WhatsAppCustomer.bsuid == bsuid,
        )
        .returning(WhatsAppCustomer.id),
    )


async def delete_sessions(db: AsyncSession, *, organization_id: UUID, identity_id: UUID) -> int:
    """Drop the chat account's sessions on the organization's bots."""
    bots = select(ChannelBot.id).where(ChannelBot.organization_id == organization_id)
    return await _affected(
        db,
        delete(ChannelSession)
        .where(ChannelSession.identity_id == identity_id, ChannelSession.bot_id.in_(bots))
        .returning(ChannelSession.id),
    )
