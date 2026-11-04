"""Commit a chat's required handback alongside the state it describes."""

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.db.models.agent_run import RunStatus
from app.services.background_jobs import enqueue
from app.services.channels.handback import STOPPED_NOTICE, ChatNotice
from app.services.transcript import RecordedToolCall
from app.worker.jobs import DELIVER_CHANNEL_HANDBACK, ChannelHandback, ChannelHandbackCall

if TYPE_CHECKING:
    from app.services.agent_runner import RunSegment


async def queue_notices(db: AsyncSession, notices: Sequence[ChatNotice]) -> None:
    for notice in notices:
        await enqueue(
            db,
            DELIVER_CHANNEL_HANDBACK,
            ChannelHandback(
                organization_id=notice.organization_id,
                run_id=notice.run_id,
                **notice.destination.model_dump(),
                output=notice.text,
                notice=True,
            ),
            organization_id=notice.organization_id,
            dedupe_key=f"channel-notice:{notice.run_id}:{notice.text}",
            concurrency_key=f"channel-handback:{notice.destination.bot_id}:{notice.destination.platform_chat_id}",
        )


def queue_segment(
    db: AsyncSession,
    destination: ChannelDestination,
    inherited: Sequence[RecordedToolCall],
) -> Callable[[RunSegment], Awaitable[None]]:
    from app.services.channels.prompts import ChannelPrompts

    # One ticket per execution, reused if its persistence callback is retried.
    ticket = uuid4()

    async def persist(segment: RunSegment) -> None:
        said = ChannelPrompts.with_inherited(segment, list(inherited))
        await enqueue(
            db,
            DELIVER_CHANNEL_HANDBACK,
            ChannelHandback(
                organization_id=segment.run.organization_id,
                run_id=segment.run.id,
                **destination.model_dump(),
                output=said.output
                or (STOPPED_NOTICE if segment.run.status == RunStatus.CANCELLED.value else ""),
                tool_calls=[
                    ChannelHandbackCall.model_validate(call, from_attributes=True)
                    for call in said.tool_calls
                ],
                generated_files=said.generated_files,
            ),
            organization_id=segment.run.organization_id,
            dedupe_key=f"channel-segment:{ticket}",
            concurrency_key=f"channel-handback:{destination.bot_id}:{destination.platform_chat_id}",
        )

    return persist
