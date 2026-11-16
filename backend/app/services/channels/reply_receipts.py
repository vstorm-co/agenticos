"""Persist a final answer before delivery; unknown submission never replays a run."""

import asyncio
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.models.channel_bot import ChannelBot
from app.db.session import get_db_context
from app.repositories import background_job as job_repo
from app.repositories import conversation_repo
from app.services import generated_media
from app.services.background_jobs import enqueue
from app.services.channels.base import IncomingMessage
from app.worker.jobs import (
    DELIVER_CHANNEL_REPLY,
    ChannelHandback,
    ChannelHandbackCall,
    ChannelHandbackFile,
)

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
    native_ids: set[str] = field(default_factory=set)
    renderer: Callable[[RunSegment], Awaitable[str]] | None = None
    rendered_output: str | None = None

    async def persist(self, segment: RunSegment) -> None:
        from app.db.models.agent_run import RunStatus
        from app.services.channels.handback import STOPPED_NOTICE
        from app.services.channels.mentions import AnsweredTurn
        from app.services.channels.router import ChannelMessageRouter, _empty_answer
        from app.services.channels.steering import current_receipt

        receipt = current_receipt()
        if receipt is not None and not await job_repo.lock_channel_message_lease(
            self.db, receipt_id=receipt
        ):
            await self.db.rollback()
            raise asyncio.CancelledError("Channel execution lease lost before terminal commit")
        self.run_id = segment.run.id
        await conversation_repo.bind_channel_source(
            self.db, run_id=self.run_id, role="user", source_id=self.incoming.message_id
        )
        self.rendered_output = (
            segment.output if self.renderer is None else await self.renderer(segment)
        )
        if not self.rendered_output:
            self.rendered_output = (
                STOPPED_NOTICE
                if segment.run.status == RunStatus.CANCELLED.value
                else _empty_answer(
                    AnsweredTurn(
                        text="",
                        status=segment.run.status,
                        awaiting_approval_run_id=segment.run.id
                        if segment.run.status == RunStatus.AWAITING_APPROVAL.value
                        else None,
                    )
                )
            )
        attachments: list[ChannelHandbackFile] = []
        for file in segment.outbound:
            admission = await generated_media.admit_generated_media(
                self.bot.organization_id, estimate_bytes=len(file.content)
            )
            if not admission.admitted:
                raise BadRequestError(
                    message="The requested reply file exceeds the organization's stored-file quota."
                )
            try:
                leaf = await generated_media.keep_generated_media(
                    self.bot.organization_id,
                    file.content,
                    filename=file.filename,
                    conversation_id=segment.run.conversation_id,
                    reservation_id=admission.reservation_id,
                )
            finally:
                if admission.reservation_id is not None:
                    await generated_media.release_generated_media(
                        self.bot.organization_id, admission.reservation_id
                    )
            attachments.append(
                ChannelHandbackFile(
                    filename=file.filename, mime_type=file.mime_type, stored_leaf=leaf
                )
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
                    self.rendered_output
                    or (STOPPED_NOTICE if segment.run.status == "cancelled" else ""),
                    self.file_refusals,
                ),
                tool_calls=[
                    ChannelHandbackCall.model_validate(call, from_attributes=True)
                    for call in segment.tool_calls
                ],
                generated_files=segment.generated_files,
                attachments=attachments,
            ),
            organization_id=self.bot.organization_id,
            # Normally the live turn sends immediately. A worker only recovers an
            # unattempted reply after the API/agent worker disappeared.
            run_after=datetime.now(UTC) + timedelta(seconds=30),
        )

    async def render(self, answer: str, *, native_id: str | None = None) -> None:
        if self.job_id is not None:
            async with get_db_context() as db:
                await job_repo.render_channel_reply(db, job_id=self.job_id, output=answer)
        if native_id is not None:
            self.native_ids.add(native_id)

    async def begin_submission(self) -> bool:
        if self.job_id is None:
            return True
        async with get_db_context() as db:
            return await job_repo.claim_channel_reply(db, job_id=self.job_id)

    async def settle(self, *, delivered: bool) -> None:
        if self.job_id is not None:
            async with get_db_context() as db:
                if self.run_id is not None:
                    for native_id in self.native_ids:
                        await conversation_repo.bind_channel_source(
                            db, run_id=self.run_id, role="assistant", source_id=native_id
                        )
                await job_repo.settle_channel_reply(db, job_id=self.job_id, delivered=delivered)


_required: ContextVar[RequiredReply | None] = ContextVar("required_channel_reply", default=None)


@contextmanager
def required_reply(reply: RequiredReply | None) -> Generator[None]:
    token = _required.set(reply)
    try:
        yield
    finally:
        _required.reset(token)


def segment_sink(
    renderer: Callable[[RunSegment], Awaitable[str]] | None = None,
) -> Callable[[RunSegment], Awaitable[None]] | None:
    reply = _required.get()
    if reply is None:
        return None
    reply.renderer = renderer
    return reply.persist


def saved_rendering() -> str | None:
    reply = _required.get()
    return None if reply is None else reply.rendered_output


async def remember_delivered_post(native_id: str | None) -> None:
    reply = _required.get()
    if reply is not None and reply.run_id is not None and native_id is not None:
        reply.native_ids.add(native_id)
