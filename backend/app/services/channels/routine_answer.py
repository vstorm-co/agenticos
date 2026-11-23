"""Posting a stored routine answer to the private chat it was asked in.

A routine created in a private chat answers into that chat's conversation. The
fire stores the answer and queues one job; this module is that job. It re-checks
everything the fire decided, because minutes can pass and the person may have
left the chat, unlinked their account or lost access since: the chat's session,
the bot, the conversation, the stored message, the person's chat account and the
same admission a chat run is held to. Any definite no leaves the answer in the
console, marks the routine's delivery `unavailable` and tells its owner.

The platform is called with no database session open, and a send that fails
escapes as a fixed error so the worker retries without a vendor's text, which
can carry a token or a URL, reaching the job row.
"""

import logging
from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ExternalServiceError
from app.db.models.agent_trigger import AgentTrigger, TriggerDeliveryStatus
from app.db.session import get_db_context
from app.repositories import (
    agent_repo,
    agent_run_repo,
    agent_trigger_repo,
    channel_identity_repo,
    channel_session_repo,
    conversation_repo,
)
from app.repositories import channel_bot as channel_bot_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import IncomingMessage, OutgoingMessage
from app.worker.jobs import RoutineChatAnswer

logger = logging.getLogger(__name__)

ROUTINE_CHAT_PLATFORMS: Final = frozenset(
    {"telegram", "slack", "mattermost", "teams", "discord", "matrix"}
)
"""The chat platforms a routine's answer is posted to. SMS, iMessage and email are not."""

_PENDING: Final = TriggerDeliveryStatus.PENDING.value


@dataclass(frozen=True)
class _Post:
    """Everything the platform call needs, read while the session was open."""

    platform: str
    token: str
    message: OutgoingMessage


def _awaiting(trigger: AgentTrigger, job: RoutineChatAnswer) -> bool:
    """Whether this job's fire is the routine's latest and still waits for its post."""
    return trigger.last_run_id == job.run_id and trigger.last_delivery_status == _PENDING


async def send_routine_answer(job: RoutineChatAnswer) -> None:
    """Post the stored answer, then read the routine's delivery as `delivered`.

    A definite refusal settles the delivery `unavailable` and returns. A platform
    failure raises for the worker's bounded retries; the settler closes the
    delivery if they run out. A job for a fire that is no longer the routine's
    latest still posts its answer but never writes a status over the newer one.
    """
    from app.services.channels.router import ChannelMessageRouter, ChatTurn

    async with get_db_context() as db:
        trigger = await agent_trigger_repo.get(
            db, job.trigger_id, organization_id=job.organization_id
        )
        if trigger is None:
            return
        if trigger.last_run_id == job.run_id and trigger.last_delivery_status != _PENDING:
            return
        creator = trigger.created_by_user_id
        session = await channel_session_repo.get_by_id(db, job.session_id)
        bot = (
            None
            if session is None
            else await channel_bot_repo.get_for_org(
                db, session.bot_id, organization_id=job.organization_id
            )
        )
        conversation = await conversation_repo.get_conversation_by_id(
            db, job.conversation_id, fresh=True
        )
        message = await conversation_repo.get_message_by_id(db, job.message_id)
        identity = (
            None
            if session is None
            else await channel_identity_repo.get_by_id(db, session.identity_id)
        )
        if (
            creator is None
            or session is None
            or not session.is_active
            or session.chat_type != "private"
            or session.conversation_id != job.conversation_id
            or bot is None
            or not bot.is_active
            or bot.platform not in ROUTINE_CHAT_PLATFORMS
            or conversation is None
            or conversation.is_archived
            or conversation.organization_id != job.organization_id
            or conversation.user_id != creator
            or message is None
            or message.conversation_id != job.conversation_id
            or message.run_id != job.run_id
            or identity is None
            or not identity.is_active
        ):
            await _settle_unavailable(db, job)
            return
        turn = ChatTurn(
            organization_id=job.organization_id,
            surface=bot.platform,
            conversation_id=session.conversation_id,
            channel_identity_id=identity.id,
            agent_id=trigger.agent_id,
            initiated_by_publisher_fallback=False,
            user_id=creator,
        )
        incoming = IncomingMessage(
            platform=identity.platform,
            bot_id=str(bot.id),
            platform_user_id=identity.platform_user_id,
            platform_chat_id=session.platform_chat_id,
            chat_type=session.chat_type,
            text="",
            raw={"server_url": identity.server_url} if identity.platform == "matrix" else {},
        )
        # A private chat is admitted from the database alone, so no platform call
        # is made while this session is open.
        admission = await ChannelMessageRouter().admission(db, turn, incoming)
        if admission.verdict != "admitted":
            await _settle_unavailable(db, job)
            return
        adapter = get_adapter(bot.platform)
        post = _Post(
            platform=bot.platform,
            token=unseal_bot_token(bot),
            message=OutgoingMessage(
                platform_chat_id=session.platform_chat_id,
                text=message.content,
                api_base_url=bot.api_base_url,
            ),
        )
    try:
        await adapter.send_message(post.token, post.message)
    except Exception:
        logger.exception(
            "routine_chat_answer_failed",
            extra={
                "trigger_id": str(job.trigger_id),
                "run_id": str(job.run_id),
                "platform": post.platform,
            },
        )
        raise ExternalServiceError(
            message="The chat platform did not accept the routine answer",
            details={"platform": post.platform},
        ) from None
    await _settle_delivered(job)


async def _settle_delivered(job: RoutineChatAnswer) -> None:
    from app.services.outcome import OutcomeService

    async with get_db_context() as db:
        trigger = await agent_trigger_repo.get(
            db, job.trigger_id, organization_id=job.organization_id, for_update=True
        )
        if trigger is None or not _awaiting(trigger, job):
            return
        trigger.last_delivery_status = TriggerDeliveryStatus.DELIVERED.value
        run = await agent_run_repo.get_run(db, job.run_id, organization_id=job.organization_id)
        await OutcomeService(db).resolve_routine_failure(
            organization_id=job.organization_id,
            user_id=trigger.created_by_user_id,
            routine_id=trigger.id,
            routine_kind="trigger",
            reason="delivery",
            recovered_at=None if run is None else run.ended_at or run.started_at,
        )


async def _settle_unavailable(db: AsyncSession, job: RoutineChatAnswer) -> None:
    """Read the delivery as `unavailable` and tell the owner, for this fire only."""
    from app.services.notifications import NotificationService

    trigger = await agent_trigger_repo.get(
        db, job.trigger_id, organization_id=job.organization_id, for_update=True
    )
    if trigger is None or not _awaiting(trigger, job):
        return
    trigger.last_delivery_status = TriggerDeliveryStatus.UNAVAILABLE.value
    run = await agent_run_repo.get_run(db, job.run_id, organization_id=job.organization_id)
    agent = await agent_repo.get(db, trigger.agent_id, organization_id=job.organization_id)
    observation = None if run is None else run.ended_at or run.started_at
    if observation is None:
        return
    await NotificationService(db).routine_blocked(
        organization_id=job.organization_id,
        owner_user_id=trigger.created_by_user_id,
        routine_id=trigger.id,
        routine_kind="trigger",
        reason="delivery",
        name=trigger.name or (agent.name if agent is not None else None),
        detail="chat_unavailable",
        observed_at=observation,
        run=run,
    )


async def settle_lost_routine_answer(job: RoutineChatAnswer, _why: str) -> None:
    """Close the delivery of a send that will not be attempted again.

    Covers exhausted retries, a dead worker, a buried job and an owner's cancel.
    """
    async with get_db_context() as db:
        await _settle_unavailable(db, job)
