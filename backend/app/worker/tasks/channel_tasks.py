"""Required chat delivery and Discord membership reconciliation."""

import logging

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.db.session import get_db_context
from app.services.channels.continuation import ChatDelivery, deliver_in_chat
from app.services.channels.discord_roles import sweep_discord_roles
from app.services.channels.handback import ChatNotice, ensure_channel_adapters, send_notice
from app.services.transcript import RecordedToolCall
from app.worker.jobs import ChannelHandback

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
                        call.tool_call_id, call.tool_name, dict(call.args), call.result
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
