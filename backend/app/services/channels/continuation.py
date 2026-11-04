"""Continue a parked chat run after somebody decided it somewhere else (#2656).

A run asked in Slack, Telegram, Mattermost, Teams or Discord parks on an approval
or a question. When a person settles the last of them in the console, the web
chat or the session API, the server continues the run as that person and posts
the answer to the chat it was asked in; the browser does not resume it as well.

Both entry points are background work: they take ids and frozen values, open a
session of their own, and persist required delivery as a job. The chat's lock
comes first, before any row lock, so nothing here waits for a chat while holding a row.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.channel_tools._directory import ChannelDestination
from app.core.audit import set_impersonator
from app.core.exceptions import AppException, RunExecutionError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus
from app.db.models.channel_bot import ChannelBot
from app.db.session import get_db_context
from app.repositories import agent_run_repo, channel_bot_repo, channel_prompt_repo
from app.services.access import decider_context
from app.services.agent_runner import AgentRunnerService, RunSegment
from app.services.channels.handback import REFUSED_NOTICE, ChatNotice, chat_destination
from app.services.channels.handback_jobs import queue_notices, queue_segment
from app.services.channels.next_steps import incoming_for_run
from app.services.channels.prompts import ChannelPrompts
from app.services.channels.router import ChannelMessageRouter, chat_lock
from app.services.transcript import RecordedToolCall

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatDelivery:
    """What a continuation said, without the run row, so it can cross a task boundary."""

    output: str
    tool_calls: tuple[RecordedToolCall, ...]
    generated_files: frozenset[str]

    @classmethod
    def of(cls, segment: RunSegment) -> ChatDelivery:
        return cls(
            output=segment.output,
            tool_calls=tuple(segment.tool_calls),
            generated_files=segment.generated_files,
        )


def _waits_on_decision(
    run: AgentRun | None, destination: ChannelDestination, approval_id: UUID
) -> bool:
    """Whether the run still waits on approval, and that approval is part of why.

    A run a person resumed by hand can have parked again on a question or on other
    calls while the continuation waited for the chat; it is theirs, not this one's.
    """
    if run is None or run.status != RunStatus.AWAITING_APPROVAL.value:
        return False
    if chat_destination(run) != destination:
        return False
    state = run.paused_state
    return isinstance(state, dict) and str(approval_id) in state.get("tool_call_ids", {})


async def continue_in_chat(
    *,
    organization_id: UUID,
    run_id: UUID,
    decider_user_id: UUID,
    impersonator_id: UUID | None,
    destination: ChannelDestination,
    approval_id: UUID,
) -> None:
    """Continue the run as the person who decided it, and post the result to its chat.

    `approval_id` is the decision that queued this. Silent when a browser, a press or
    another decider got there first, or the run waits on something else now. A definite
    refusal (the decider or the chat no longer admits the run, or the run cannot
    be built again) posts `REFUSED_NOTICE` once and stamps the run, so the safety
    net does not say it twice. Never raises.
    """
    bot_id = destination.bot_id
    try:
        # `spawn` clears the impersonator, so the continuation names it again.
        set_impersonator(impersonator_id)
        async with chat_lock(str(bot_id), destination.platform_chat_id), get_db_context() as db:
            await _attempt(
                db,
                organization_id=organization_id,
                run_id=run_id,
                decider_user_id=decider_user_id,
                destination=destination,
                approval_id=approval_id,
            )

    except Exception:
        logger.exception("channel_continuation_failed run_id=%s bot_id=%s", run_id, bot_id)


async def _attempt(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    decider_user_id: UUID,
    destination: ChannelDestination,
    approval_id: UUID,
) -> None:
    """Continue once and persist the result or refusal for delivery after commit."""
    bot_id = destination.bot_id
    bot = await channel_bot_repo.get_for_org(db, bot_id, organization_id=organization_id)
    if bot is None or not bot.is_active:
        logger.info("channel_continuation_bot_off run_id=%s bot_id=%s", run_id, bot_id)
        return None
    run = await agent_run_repo.get_run(db, run_id, organization_id=organization_id)
    if run is None or not _waits_on_decision(run, destination, approval_id):
        logger.info("channel_continuation_moved_on run_id=%s bot_id=%s", run_id, bot_id)
        return None
    decider = await decider_context(db, organization_id=organization_id, user_id=decider_user_id)
    # Network-bound, so it runs before the row lock is taken.
    refusal = await _refusal(db, run, bot, destination, decider)
    claimed = await agent_run_repo.claim_parked_run(db, run_id, organization_id=organization_id)
    if claimed is None or not _waits_on_decision(claimed, destination, approval_id):
        logger.info("channel_continuation_moved_on run_id=%s bot_id=%s", run_id, bot_id)
        return None
    pending = await agent_run_repo.list_approvals_for_run(
        db, run_id=run_id, organization_id=organization_id
    )
    if any(approval.status == ApprovalStatus.PENDING.value for approval in pending):
        return None
    if refusal is not None or decider is None:
        return await _refuse(db, claimed, destination, refusal or "decider_unavailable")
    inherited = ChannelPrompts.inherited_calls(claimed)
    savepoint = await db.begin_nested()
    try:
        await channel_prompt_repo.settle_open(db, run_id=run_id, by="continued")
        await AgentRunnerService(db).resume(
            decider, run_id, on_segment=queue_segment(db, destination, inherited)
        )
    except RunExecutionError:
        # The terminal transaction already queued the failure delivery.
        return None
    except AppException as exc:
        if savepoint.is_active:
            await savepoint.rollback()
        return await _refuse(db, claimed, destination, type(exc).__name__)
    if savepoint.is_active:
        await savepoint.commit()
    return None


async def _refusal(
    db: AsyncSession,
    run: AgentRun,
    bot: ChannelBot,
    destination: ChannelDestination,
    decider: AuthContext | None,
) -> str | None:
    """Why the continuation must not run, or None. Only a definite no counts."""
    if decider is None:
        return "decider_unavailable"
    if not decider.has(Perm.APPROVALS_DECIDE):
        return "decider_cannot_decide"
    incoming = await incoming_for_run(
        db, run, bot_id=bot.id, platform_chat_id=destination.platform_chat_id
    )
    if incoming is None:
        return "chat_moved_on"
    admission = await ChannelMessageRouter().admission(db, run, incoming)
    if admission.verdict == "refused":
        return admission.reason
    if admission.verdict == "unconfirmed":
        logger.warning(
            "channel_continuation_unconfirmed run_id=%s bot_id=%s reason=%s",
            run.id,
            bot.id,
            admission.reason,
        )
    return None


async def _refuse(
    db: AsyncSession, run: AgentRun, destination: ChannelDestination, reason: str
) -> None:
    """Stamp the run and queue its notice, unless this park was already told."""
    bot_id = destination.bot_id
    logger.info(
        "channel_continuation_refused run_id=%s bot_id=%s reason=%s", run.id, bot_id, reason
    )
    if run.chat_notice_sent_at is not None:
        return
    await agent_run_repo.record_chat_notice(db, run=run, at=datetime.now(UTC))
    await queue_notices(db, [ChatNotice(run.organization_id, run.id, destination, REFUSED_NOTICE)])
    return


async def deliver_in_chat(
    *,
    organization_id: UUID,
    run_id: UUID,
    destination: ChannelDestination,
    said: ChatDelivery,
) -> None:
    """Post a continuation somebody ran by hand (Resume, an answer) to its chat.

    The run already ran and committed, so a room that definitely no longer admits
    the asker, or a chat that started over, gets nothing. Transport failures are retried by the worker.
    """
    bot_id = destination.bot_id
    async with chat_lock(str(bot_id), destination.platform_chat_id), get_db_context() as db:
        await _post_if_admitted(
            db,
            organization_id=organization_id,
            run_id=run_id,
            destination=destination,
            said=said,
        )


async def _post_if_admitted(
    db: AsyncSession,
    *,
    organization_id: UUID,
    run_id: UUID,
    destination: ChannelDestination,
    said: ChatDelivery,
) -> None:
    bot_id = destination.bot_id
    bot = await channel_bot_repo.get_for_org(db, bot_id, organization_id=organization_id)
    if bot is None or not bot.is_active:
        return
    run = await agent_run_repo.get_run(db, run_id, organization_id=organization_id)
    if run is None:
        return
    incoming = await incoming_for_run(
        db, run, bot_id=bot_id, platform_chat_id=destination.platform_chat_id
    )
    if incoming is None:
        logger.info("channel_delivery_chat_moved_on run_id=%s bot_id=%s", run_id, bot_id)
        return
    admission = await ChannelMessageRouter().admission(db, run, incoming)
    if admission.verdict == "refused":
        logger.info(
            "channel_delivery_refused run_id=%s bot_id=%s reason=%s",
            run_id,
            bot_id,
            admission.reason,
        )
        return
    if admission.verdict == "unconfirmed":
        logger.warning(
            "channel_delivery_unconfirmed run_id=%s bot_id=%s reason=%s",
            run_id,
            bot_id,
            admission.reason,
        )
    segment = RunSegment(
        output=said.output,
        run=run,
        tool_calls=list(said.tool_calls),
        settled={},
        generated_files=said.generated_files,
    )
    await ChannelPrompts(db).deliver(
        bot,
        platform=run.surface,
        platform_chat_id=destination.platform_chat_id,
        segment=segment,
    )
