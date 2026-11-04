"""Retry required chat delivery without repeating a model or an approved action."""

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.services.channels.continuation import ChatDelivery, deliver_in_chat
from app.services.channels.handback import ChatNotice, ensure_channel_adapters, send_notice
from app.services.transcript import RecordedToolCall
from app.worker.jobs import ChannelHandback


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
