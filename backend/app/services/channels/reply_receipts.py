"""Persist a final answer before delivery; unknown submission never replays a run."""

from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.db.session import get_db_context
from app.repositories import background_job as job_repo
from app.repositories import conversation_repo
from app.services.background_jobs import enqueue
from app.services.channels.base import IncomingMessage
from app.worker.jobs import DELIVER_CHANNEL_REPLY, ChannelHandback, ChannelHandbackCall

if TYPE_CHECKING:
    from app.services.agent_runner import RunSegment


@dataclass
class RequiredReply:
    db: AsyncSession
    bot: ChannelBot
    incoming: IncomingMessage
    file_refusals: list[str] = field(default_factory=list)
    job_id: UUID | None = None
    run_id: UUID | None = None

    async def persist(self, segment: RunSegment) -> None:
        from app.services.channels.handback import STOPPED_NOTICE
        from app.services.channels.router import ChannelMessageRouter

        self.run_id = segment.run.id
        await conversation_repo.bind_channel_source(
            self.db, run_id=self.run_id, role="user", source_id=self.incoming.message_id
        )
        self.job_id = await enqueue(
            self.db,
            DELIVER_CHANNEL_REPLY,
            ChannelHandback(
                initial_reply_id=uuid4(),
                organization_id=self.bot.organization_id,
                run_id=segment.run.id,
                bot_id=self.bot.id,
                platform_chat_id=self.incoming.platform_chat_id,
                private_chat=self.incoming.chat_type == "private",
                message_id=self.incoming.message_id,
                output=ChannelMessageRouter._with_notes(
                    segment.output or (STOPPED_NOTICE if segment.run.status == "cancelled" else ""),
                    self.file_refusals,
                ),
                tool_calls=[
                    ChannelHandbackCall.model_validate(call, from_attributes=True)
                    for call in segment.tool_calls
                ],
                generated_files=segment.generated_files,
            ),
            organization_id=self.bot.organization_id,
            # Normally the live turn sends immediately. A worker only recovers an
            # unattempted reply after the API/agent worker disappeared.
            run_after=datetime.now(UTC) + timedelta(seconds=30),
        )

    async def begin_submission(self) -> bool:
        if self.job_id is None:
            return True
        async with get_db_context() as db:
            return await job_repo.claim_channel_reply(db, job_id=self.job_id)

    async def settle(self, *, delivered: bool) -> None:
        if self.job_id is not None:
            async with get_db_context() as db:
                await job_repo.settle_channel_reply(db, job_id=self.job_id, delivered=delivered)


_required: ContextVar[RequiredReply | None] = ContextVar("required_channel_reply", default=None)


@contextmanager
def required_reply(reply: RequiredReply | None) -> Generator[None]:
    token = _required.set(reply)
    try:
        yield
    finally:
        _required.reset(token)


def segment_sink() -> Callable[[RunSegment], Awaitable[None]] | None:
    reply = _required.get()
    return None if reply is None else reply.persist


async def remember_delivered_post(native_id: str | None) -> None:
    reply = _required.get()
    if reply is not None and reply.run_id is not None and native_id is not None:
        await conversation_repo.bind_channel_source(
            reply.db, run_id=reply.run_id, role="assistant", source_id=native_id
        )
