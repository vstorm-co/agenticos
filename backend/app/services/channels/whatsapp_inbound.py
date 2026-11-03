"""What happens to a verified WhatsApp batch: record the window, then queue the work (#2076).

The webhook route has checked the signature before it calls `receive`, so nothing
here is written for a forged body. `receive` runs in the request's transaction:
each customer's latest Meta message timestamp is recorded in it, and the customer's
messages are queued with `spawn_after_commit`, so the work behind them reads the
committed timestamp.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn_after_commit
from app.db.models.channel_bot import ChannelBot
from app.repositories import whatsapp_customer_repo
from app.services.channels.whatsapp_payload import (
    ParsedWebhook,
    WhatsAppMessage,
    group_by_customer,
    to_event,
)
from app.worker.background.channel import process_channel_events_in_order


class WhatsAppInbound:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def receive(self, bot: ChannelBot, parsed: ParsedWebhook) -> None:
        """Record every customer's latest message time, then queue each customer's batch.

        The time is Meta's own `timestamp` on the message, written for every message
        that parsed - a tap, a sender the router will refuse - and never for a status.
        Customers are written in `bsuid` order so two batches cannot deadlock on
        each other's rows.
        """
        latest: dict[str, datetime] = {}
        for message in parsed.messages:
            latest[message.bsuid] = max(message.sent_at, latest.get(message.bsuid, message.sent_at))
        for bsuid in sorted(latest):
            await whatsapp_customer_repo.record_inbound(
                self.db,
                organization_id=bot.organization_id,
                bot_id=bot.id,
                bsuid=bsuid,
                sent_at=latest[bsuid],
            )
        for group in group_by_customer(parsed.messages):
            spawn_after_commit(
                self.db,
                handle_customer(str(bot.id), bot.organization_id, group[0].bsuid, group),
                name=f"whatsapp_events:{bot.id}",
            )


async def handle_customer(
    bot_id: str, organization_id: UUID, chat_id: str, messages: list[WhatsAppMessage]
) -> None:
    """Route one customer's messages and taps, oldest first."""
    events = [
        to_event(message, bot_id=bot_id, organization_id=organization_id) for message in messages
    ]
    await process_channel_events_in_order(events)
