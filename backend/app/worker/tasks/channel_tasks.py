"""Required chat delivery and Discord membership reconciliation."""

import json
import logging
from dataclasses import replace

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.db.session import get_db_context
from app.services.channels.base import IncomingMessage
from app.services.channels.continuation import ChatDelivery, deliver_in_chat
from app.services.channels.discord_roles import sweep_discord_roles
from app.services.channels.handback import ChatNotice, ensure_channel_adapters, send_notice
from app.services.transcript import RecordedToolCall
from app.worker.jobs import ChannelDelivery, ChannelHandback, EmailDelivery

logger = logging.getLogger(__name__)


async def deliver_handback(job: ChannelHandback) -> None:
    ensure_channel_adapters()
    destination = ChannelDestination(
        bot_id=job.bot_id,
        platform_chat_id=job.platform_chat_id,
        private_chat=job.private_chat,
    )
    if job.notice:
        await send_notice(ChatNotice(job.organization_id, job.run_id, destination, job.output))
    else:
        await deliver_in_chat(
            organization_id=job.organization_id,
            run_id=job.run_id,
            destination=destination,
            said=ChatDelivery(
                output=job.output,
                tool_calls=tuple(
                    RecordedToolCall(
                        call.tool_call_id,
                        call.tool_name,
                        dict(call.args),
                        call.result,
                        call.tool_id,
                        call.presentation_kind,
                    )
                    for call in job.tool_calls
                ),
                generated_files=job.generated_files,
            ),
        )


async def sync_discord_roles() -> dict[str, int]:
    """Reconcile everybody a Discord role placed with the roles they hold now (#2569)."""
    counts = await sweep_discord_roles(get_db_context)
    if counts["unreadable"]:
        logger.warning("Discord role sync: %d person(s) could not be checked", counts["unreadable"])
    if counts["failed"]:
        logger.error("Discord role sync: %d person(s) failed", counts["failed"])
    return counts


async def process_email_delivery(job: EmailDelivery) -> None:
    """Rehydrate files from the durable payload even after their cache TTL or an API restart."""
    from app.repositories import channel_bot_repo
    from app.services.channel_bot import unseal_bot_token
    from app.services.channels import email_state
    from app.services.channels.email import EmailAdapter, keep_inbound

    ensure_channel_adapters()
    async with get_db_context() as db:
        bot = await channel_bot_repo.get_for_inbound(db, job.bot_id)
        if (
            bot is None
            or not bot.is_active
            or bot.organization_id != job.organization_id
            or bot.platform != "email"
        ):
            return
        incoming = EmailAdapter().parse_incoming(json.loads(job.body), str(job.bot_id))
        if incoming is None:
            raise ValueError("Stored email delivery is no longer valid")
        incoming.attachments = [
            replace(item, handle=handle)
            for item, handle in zip(incoming.attachments, job.attachment_handles, strict=True)
        ]
        address = unseal_bot_token(bot).strip().lower()
        thread = await keep_inbound(address, incoming, incoming.raw)
        if thread is None:
            raise RuntimeError("Email attachment cache is at capacity")
        try:
            with email_state.replying_to(address, incoming.platform_chat_id, thread):
                await _route_inbound(incoming, db)
        finally:
            with anyio.CancelScope(shield=True):
                await email_state.discard_attachments(job.attachment_handles)


async def process_channel_delivery(job: ChannelDelivery) -> None:
    from app.repositories import channel_bot_repo
    from app.services.channels import get_adapter

    ensure_channel_adapters()
    async with get_db_context() as db:
        bot = await channel_bot_repo.get_for_inbound(db, job.bot_id)
        if (
            bot is None
            or not bot.is_active
            or bot.organization_id != job.organization_id
            or bot.platform != job.platform
        ):
            return
        if job.platform == "imessage" and not bot.webhook_mode:
            return
        incoming = get_adapter(job.platform).parse_incoming(job.payload, str(job.bot_id))
        if incoming is not None:
            await _route_inbound(incoming, db)


async def _route_inbound(incoming: IncomingMessage, db: AsyncSession) -> None:
    from app.services.channels import sms_prompts
    from app.services.channels.base import IncomingPress, read_feedback
    from app.services.channels.feedback import ChannelFeedback
    from app.services.channels.next_steps import ChannelNextSteps, read_next
    from app.services.channels.prompts import ChannelPrompts
    from app.services.channels.router import ChannelMessageRouter
    from app.services.channels.sms_links import link_has_lapsed

    text = (
        incoming.text.splitlines()[0]
        if incoming.platform == "email" and incoming.text
        else incoming.text
    )
    choice = (
        await sms_prompts.answer(
            incoming.bot_id, incoming.platform_chat_id, text, platform=incoming.platform
        )
        if not incoming.attachments or incoming.platform == "email"
        else None
    )
    if (
        choice is not None
        and incoming.platform == "sms"
        and await link_has_lapsed(incoming.platform_user_id)
    ):
        await sms_prompts.forget(incoming.bot_id, incoming.platform_chat_id)
        choice = None
    if choice is None:
        await ChannelMessageRouter().route(incoming, db)
        return
    press = IncomingPress(
        platform=incoming.platform,
        bot_id=incoming.bot_id,
        platform_user_id=incoming.platform_user_id,
        platform_chat_id=incoming.platform_chat_id,
        value=choice,
        message_id=incoming.message_id,
    )
    if read_feedback(press.value) is not None:
        await ChannelFeedback(db).rate(press)
    elif read_next(press.value) is not None:
        said = await ChannelNextSteps(db).take(press)
        if said is not None:
            await ChannelMessageRouter().route(said, db)
    else:
        await ChannelPrompts(db).press(press)
