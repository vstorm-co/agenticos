"""What happens to a verified WhatsApp batch, and to a customer who writes again (#2076).

The webhook route has checked the signature before it calls `receive`, so nothing
here is written for a forged body. `receive` runs in the request's transaction:
each customer's latest Meta message timestamp is recorded in it, and the customer's
messages are queued with `spawn_after_commit`, so the work behind them reads the
committed timestamp.

When a customer writes after a run's answer was held outside the 24-hour window,
`handle_customer` sends the held answers first, oldest first, then routes the
batch - always - and only then offers again the prompts the held runs still wait
on. That order is the point: a question offered before the batch is routed would
take the message that triggered it as its answer. The delivery and the prompts run
under the chat's lock, which is released while the batch is routed because
`route` takes it itself.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn_after_commit
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.channel_bot import ChannelBot
from app.db.models.conversation import Message
from app.db.session import get_db_context
from app.repositories import (
    agent_run_repo,
    channel_bot_repo,
    channel_session_repo,
    conversation_repo,
    whatsapp_customer_repo,
)
from app.services.channel_bot import unseal_bot_token, unseal_webhook_secret
from app.services.channels.base import OutgoingMessage
from app.services.channels.dedupe import claim_delivery
from app.services.channels.handback import NOTICES
from app.services.channels.next_steps import incoming_for_run
from app.services.channels.prompts import ChannelPrompts
from app.services.channels.router import ChannelMessageRouter, chat_lock
from app.services.channels.whatsapp import whatsapp_adapter
from app.services.channels.whatsapp_customers import Held, WindowStore
from app.services.channels.whatsapp_graph import CLOSED_WINDOW_CODE
from app.services.channels.whatsapp_payload import (
    ParsedWebhook,
    WhatsAppMessage,
    group_by_customer,
    parse_webhook,
    to_event,
    to_incoming,
    verify_signature,
)
from app.services.channels.whatsapp_window import FILES_NOT_DELIVERED
from app.worker.background.channel import process_channel_events_in_order

logger = logging.getLogger(__name__)

_PARKED = frozenset({RunStatus.AWAITING_APPROVAL.value, RunStatus.AWAITING_ANSWER.value})
_NO_ANSWER = "Done."


def _now() -> datetime:
    """The clock, named so a test can freeze it."""
    return datetime.now(UTC)


def _run_id(callback: str | None) -> UUID | None:
    try:
        return UUID(callback) if callback else None
    except ValueError:
        return None


def log_parsed(
    bot: ChannelBot, parsed: ParsedWebhook, *, routed: int = 0, owner: bool = False
) -> None:
    """Log what a parsed batch dropped for one bot.

    `routed` is how many foreign changes were handed to the bots that own them: they
    are not dropped. `owner` marks a bot that was handed its own changes: the other
    changes in the body belong to the URL bot and are not its to report, so its
    record counts no foreign changes. Counts only: a dropped message's content can
    carry a customer's number.
    """
    foreign = 0 if owner else parsed.foreign - routed
    if foreign or parsed.unidentified:
        logger.warning(
            "whatsapp_webhook_dropped",
            extra={
                "bot_id": str(bot.id),
                "foreign": foreign,
                "unidentified": parsed.unidentified,
            },
        )
    if parsed.stale or parsed.ignored:
        logger.info(
            "whatsapp_webhook_dropped",
            extra={"bot_id": str(bot.id), "stale": parsed.stale, "ignored": parsed.ignored},
        )
    for status in parsed.statuses:
        if status.status == "failed":
            # Never the wamid: it is base64 of ids that include the customer's number.
            logger.info(
                "whatsapp_status_failed",
                extra={
                    "bot_id": str(bot.id),
                    "status": "failed",
                    "codes": list(status.error_codes),
                },
            )


class WhatsAppInbound:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def route_others(
        self,
        url_bot: ChannelBot,
        body: bytes,
        signature: str | None,
        payload: Mapping[str, Any],
        parsed: ParsedWebhook,
        *,
        now: datetime,
    ) -> int:
        """Hand each change for another number to the bot that owns it; returns the changes routed.

        One Meta app serves several numbers through one callback URL, and each bot
        keeps its own app secret. A bot is given a change only when *its own* secret
        verifies the body, so the URL bot's signature never admits a change on its
        own: routing takes bots on numbers of the same Meta app, which hold the same
        app secret. Exactly one such bot may own a number: none, or several, and the
        change is dropped and logged. A bot whose secret cannot be read is not
        admitted, and does not fail the batch. The owner may belong to another
        organization; the signature is the rule.

        Raises:
            Exception: Whatever `receive` raised for a routed bot. It fails the whole
                batch, as for the URL bot, and Meta delivers it again.
        """
        if not parsed.others:
            return 0
        owners = await channel_bot_repo.get_active_whatsapp_by_numbers(self.db, pairs=parsed.others)
        routed = 0
        for account_id, phone_number_id in parsed.others:
            candidates = [
                bot
                for bot in owners
                if bot.id != url_bot.id
                and (bot.whatsapp_account_id, bot.whatsapp_phone_number_id)
                == (account_id, phone_number_id)
            ]
            admitted: list[ChannelBot] = []
            for bot in candidates:
                try:
                    secret = unseal_webhook_secret(bot)
                    if secret and verify_signature(body, signature, secret):
                        admitted.append(bot)
                except Exception as exc:
                    logger.warning(
                        "whatsapp_owner_secret_unreadable",
                        extra={
                            "bot_id": str(url_bot.id),
                            "owner_id": str(bot.id),
                            "phone_number_id": phone_number_id,
                            "error": type(exc).__name__,
                        },
                    )
            if len(admitted) > 1:
                logger.warning(
                    "whatsapp_number_ambiguous",
                    extra={
                        "bot_id": str(url_bot.id),
                        "phone_number_id": phone_number_id,
                        "count": len(admitted),
                    },
                )
                continue
            if not admitted:
                logger.warning(
                    "whatsapp_number_unrouted",
                    extra={
                        "bot_id": str(url_bot.id),
                        "phone_number_id": phone_number_id,
                    },
                )
                continue
            (owner,) = admitted
            for_owner = parse_webhook(
                payload, phone_number_id=phone_number_id, account_id=account_id, now=now
            )
            log_parsed(owner, for_owner, owner=True)
            await self.receive(owner, for_owner)
            routed += for_owner.own
        return routed

    async def receive(self, bot: ChannelBot, parsed: ParsedWebhook) -> None:
        """Record every customer's latest message time, then queue each customer's batch.

        The time is Meta's own `timestamp` on the message, written for every message
        that parsed - a tap, a sender the router will refuse - and never for a status.
        Customers are written in `bsuid` order so two batches cannot deadlock on
        each other's rows.

        Raises:
            Exception: Whatever the store raised for a customer that could not be
                recorded. It fails the whole batch and nothing is queued, so the
                route answers 500 and Meta delivers the batch again.
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
        self._queue_closed_window_statuses(bot, parsed)

    def _queue_closed_window_statuses(self, bot: ChannelBot, parsed: ParsedWebhook) -> None:
        """Act on a `failed` status only for the run its callback data names.

        Meta's 131047 on a status means the window was closed for a message we sent.
        Which run that was is whatever the status echoes of `biz_opaque_callback_data`;
        a status that names none is only logged, never guessed at.
        """
        closed: dict[tuple[str, UUID], datetime | None] = {}
        for status in parsed.statuses:
            if status.status != "failed":
                continue
            run_id = _run_id(status.callback)
            if CLOSED_WINDOW_CODE not in status.error_codes:
                if run_id is not None:
                    logger.warning(
                        "whatsapp_send_failed",
                        extra={
                            "bot_id": str(bot.id),
                            "run_id": str(run_id),
                            "codes": list(status.error_codes),
                        },
                    )
                continue
            if run_id is None or status.recipient is None:
                logger.warning("whatsapp_closed_window_unattributed", extra={"bot_id": str(bot.id)})
                continue
            key = (status.recipient, run_id)
            seen = closed.get(key)
            closed[key] = max(status.at, seen) if status.at and seen else status.at or seen
        for (chat_id, run_id), at in closed.items():
            spawn_after_commit(
                self.db,
                reclaim_after_refusal(str(bot.id), bot.organization_id, chat_id, run_id, at),
                name=f"whatsapp_window_closed:{bot.id}",
            )


async def handle_customer(
    bot_id: str,
    organization_id: UUID,
    chat_id: str,
    messages: list[WhatsAppMessage],
    *,
    store: WindowStore | None = None,
) -> None:
    """Deliver what was held for the customer, route their messages, then offer prompts again.

    The held-answer code can fail without costing the customer their message: the
    batch is routed whatever happens before it. The lock is taken only when
    something is held, so a message that steers a running turn never waits behind it.
    """
    store = store or WindowStore()
    delivered: list[Held] = []
    try:
        if await store.has_held(bot_id, chat_id, now=_now()):
            async with chat_lock(bot_id, chat_id):
                await _deliver_answers(bot_id, organization_id, chat_id, store, delivered)
    except Exception as failure:
        logger.warning(
            "whatsapp_held_failed", extra={"bot_id": bot_id, "error": type(failure).__name__}
        )
    # A tap on the template's own quick-reply button asked for the answer that was just
    # sent; any other button tap is a message like another and is routed.
    show_me = await _template_button(bot_id, store) if any(h.answer for h in delivered) else None
    events = []
    for message in messages:
        if (
            message.kind == "button"
            and message.reply_id is None
            and show_me is not None
            and message.text == show_me
        ):
            # Dropped, but still taken, so a redelivery of it is not routed as a new turn later.
            await claim_delivery(
                to_incoming(message, bot_id=bot_id, organization_id=organization_id)
            )
            continue
        events.append(to_event(message, bot_id=bot_id, organization_id=organization_id))
    if events:
        await process_channel_events_in_order(events)
    owing = [held for held in delivered if held.prompts_owed]
    if not owing:
        return
    try:
        async with chat_lock(bot_id, chat_id):
            await _offer_again(bot_id, organization_id, chat_id, owing, store)
    except Exception as failure:
        logger.warning(
            "whatsapp_offer_failed", extra={"bot_id": bot_id, "error": type(failure).__name__}
        )
        for held in owing:
            await store.release(held)


async def _template_button(bot_id: str, store: WindowStore) -> str | None:
    """The bot's late-answer template's quick-reply label; `None` when it has none or cannot be read."""
    try:
        template = await store.late_template(bot_id)
    except Exception as failure:
        logger.warning(
            "whatsapp_template_unread", extra={"bot_id": bot_id, "error": type(failure).__name__}
        )
        return None
    return template.button if template is not None else None


@dataclass(frozen=True)
class _Owed:
    """What one held run needs, read in one session so the session is closed before any send."""

    admitted: bool
    parked: bool
    text: str


async def _read_run(
    db: AsyncSession, run: AgentRun, held: Held, *, bot_id: str, organization_id: UUID, chat_id: str
) -> _Owed:
    # The run's own sender, judged as a decision's continuation is: only a definite
    # refusal keeps the answer held, never what the platform could not confirm.
    incoming = await incoming_for_run(db, run, bot_id=UUID(bot_id), platform_chat_id=chat_id)
    admitted = (
        incoming is not None
        and (await ChannelMessageRouter().admission(db, run, incoming)).verdict != "refused"
    )
    return _Owed(
        admitted=admitted,
        parked=run.status in _PARKED,
        text=(await _owed_answer(db, run, held, organization_id) if held.answer else _NO_ANSWER),
    )


def _saved(message: Message | None) -> str:
    """A saved answer as it was saved, or `"Done."` when there is none.

    The router's notes are not saved, so they are not sent again.
    """
    content = message.content if message is not None else ""
    return content if content.strip() else _NO_ANSWER


async def _owed_answer(db: AsyncSession, run: AgentRun, held: Held, organization_id: UUID) -> str:
    """The exact answer the row owes, by the id of the message saved when it was held."""
    if held.message_id is None:
        return _NO_ANSWER
    return _saved(
        await conversation_repo.answer_message(
            db, held.message_id, run_id=run.id, organization_id=organization_id
        )
    )


async def _latest_answer(db: AsyncSession, run: AgentRun) -> str:
    """The run's latest saved answer, for the preview of an answer Meta has just refused."""
    return _saved(
        await conversation_repo.last_answer_message(db, run.id, organization_id=run.organization_id)
    )


async def _bot_token(bot_id: str, organization_id: UUID) -> str | None:
    """The bot's token, or `None` when the bot is gone or switched off."""
    async with get_db_context() as db:
        bot = await channel_bot_repo.get_for_org(db, UUID(bot_id), organization_id=organization_id)
        return unseal_bot_token(bot) if bot is not None and bot.is_active else None


def _log_held_failure(event: str, bot_id: str, run_id: UUID, failure: Exception) -> None:
    logger.warning(
        event, extra={"bot_id": bot_id, "run_id": str(run_id), "error": type(failure).__name__}
    )


async def _deliver_answers(
    bot_id: str,
    organization_id: UUID,
    chat_id: str,
    store: WindowStore,
    delivered: list[Held] | None = None,
) -> list[Held]:
    """Send the customer's held answers, oldest first; the caller holds the chat's lock.

    Each row owes one saved answer, sent once by its own message id; a run held twice
    sends both, in the order they were held. A row may also owe a fixed notice
    sentence, sent after its answer whatever the run's status; a notice that cannot
    be delivered (the run or its sender is gone) is dropped, never held.

    A row leaves the claim only when its answer was sent, its run moved on, or a
    later step settles it. Whatever is not settled when this returns is given
    back with its flags and reason intact: a sender who is no longer admitted, a
    send that failed, a crash. Returns the rows whose answer was sent and those
    that still owe prompts; with `delivered` given, they are appended to it as they
    settle, so a failure part-way still leaves the caller what was done.
    """
    claimed = await store.claim_held(bot_id, chat_id, now=_now())
    pending = list(claimed)
    # A run's prompts are offered once, after its last row: every row of it but that
    # one only owes what it was holding.
    last_of_run = {held.run_id: held.id for held in claimed}
    delivered = [] if delivered is None else delivered
    try:
        if not claimed or await store.window(bot_id, chat_id, now=_now()) is False:
            return []
        token = await _bot_token(bot_id, organization_id)
        if token is None:
            return []
        for held in claimed:
            async with get_db_context() as db:
                run = await agent_run_repo.get_run(db, held.run_id, organization_id=organization_id)
                owed = (
                    await _read_run(
                        db,
                        run,
                        held,
                        bot_id=bot_id,
                        organization_id=organization_id,
                        chat_id=chat_id,
                    )
                    if run is not None
                    else None
                )
            if owed is None:
                await store.done(held)
                pending.remove(held)
                continue
            # A notice that is no longer deliverable is dropped, as `send_notice` drops it;
            # an answer waits for the sender to be admitted again.
            notice_only = held.notice is not None and not held.answer
            if not owed.admitted and not notice_only:
                logger.info(
                    "whatsapp_held_not_admitted",
                    extra={"bot_id": bot_id, "run_id": str(held.run_id)},
                )
                continue
            prompts_owed = owed.admitted and owed.parked and last_of_run[held.run_id] == held.id
            sentence = NOTICES.get(held.notice) if held.notice is not None else None
            if held.notice is not None and sentence is None:
                logger.warning(
                    "whatsapp_held_notice_unknown",
                    extra={"bot_id": bot_id, "run_id": str(held.run_id), "notice": held.notice},
                )
            sends_notice = sentence is not None and owed.admitted
            try:
                if held.answer:
                    text = f"{owed.text}\n\n{FILES_NOT_DELIVERED}" if held.files else owed.text
                    await whatsapp_adapter().send_message(
                        token,
                        OutgoingMessage(
                            platform_chat_id=chat_id, text=text, run_id=str(held.run_id)
                        ),
                    )
            except Exception as failure:
                _log_held_failure("whatsapp_held_send_failed", bot_id, held.run_id, failure)
                break
            if held.answer and sends_notice:
                # Settled before the notice goes: a failed notice must not send the answer again.
                try:
                    await store.answer_sent(held, prompts_owed=prompts_owed, keep_notice=True)
                except Exception as failure:
                    _log_held_failure("whatsapp_held_settle_failed", bot_id, held.run_id, failure)
                    break
            if sends_notice:
                try:
                    await whatsapp_adapter().send_message(
                        token,
                        OutgoingMessage(
                            platform_chat_id=chat_id,
                            text=sentence,
                            run_id=str(held.run_id),
                            notice=held.notice,
                        ),
                    )
                except Exception as failure:
                    _log_held_failure("whatsapp_held_send_failed", bot_id, held.run_id, failure)
                    break
            if held.answer and not sends_notice:
                await store.answer_sent(held, prompts_owed=prompts_owed)
                pending.remove(held)
                delivered.append(replace(held, prompts_owed=prompts_owed))
            elif prompts_owed:
                if held.notice is not None:
                    await store.notice_sent(held)
                pending.remove(held)
                delivered.append(replace(held, prompts_owed=True))
            elif not owed.admitted and owed.parked and last_of_run[held.run_id] == held.id:
                # The notice is dropped but the run's prompts stay held for a later delivery.
                await store.notice_sent(held)
            else:
                await store.done(held)
                pending.remove(held)
                if held.answer:
                    delivered.append(replace(held, prompts_owed=False))
        return delivered
    finally:
        for held in pending:
            await store.release(held)


async def _offer_again(
    bot_id: str, organization_id: UUID, chat_id: str, held: list[Held], store: WindowStore
) -> None:
    """Offer again what each run still waits on, then settle its row.

    `ChannelPrompts.offer` never raises and says whether everything was offered. A
    row is dropped when it was, or when nothing is left to offer (the bot is off, or
    the run is gone or no longer parked); otherwise the claim is given back so the
    next delivery tries again. A re-offer that keeps failing is released every time,
    so each customer message re-sends the prompts that did arrive (`resend=True`)
    until the run moves on.
    """
    for row in held:
        offered = True
        try:
            async with get_db_context() as db:
                bot = await channel_bot_repo.get_for_org(
                    db, UUID(bot_id), organization_id=organization_id
                )
                run = await agent_run_repo.get_run(db, row.run_id, organization_id=organization_id)
                if bot is not None and bot.is_active and run is not None and run.status in _PARKED:
                    offered = await ChannelPrompts(db).offer(
                        bot,
                        platform="whatsapp",
                        platform_chat_id=chat_id,
                        run_id=run.id,
                        resend=True,
                    )
        except Exception as failure:
            offered = False
            error = type(failure).__name__
        else:
            error = None
        if offered:
            await store.done(row)
            continue
        logger.warning(
            "whatsapp_offer_failed",
            extra={"bot_id": bot_id, "run_id": str(row.run_id), "error": error},
        )
        await store.release(row)


async def reclaim_after_refusal(
    bot_id: str,
    organization_id: UUID,
    chat_id: str,
    run_id: UUID,
    at: datetime | None,
    *,
    store: WindowStore | None = None,
) -> None:
    """Meta said a message of this run reached a closed window: hold the run and act on it.

    `at` is Meta's own time on the status, or `None` when it sent none. Never raises; a failure is logged by type. The run comes from Meta's echo of
    our own callback data, so it is trusted only after it is found in this bot's
    organization and in this customer's chat.
    """
    store = store or WindowStore()
    try:
        await _reclaim(bot_id, organization_id, chat_id, run_id, at, store)
    except Exception as failure:
        logger.warning(
            "whatsapp_reclaim_failed",
            extra={"bot_id": bot_id, "run_id": str(run_id), "error": type(failure).__name__},
        )


async def _reclaim(
    bot_id: str,
    organization_id: UUID,
    chat_id: str,
    run_id: UUID,
    at: datetime | None,
    store: WindowStore,
) -> None:
    async with get_db_context() as db:
        run = await agent_run_repo.get_run(db, run_id, organization_id=organization_id)
        session = await channel_session_repo.get_by_bot_and_chat(db, UUID(bot_id), chat_id)
        if (
            run is None
            or run.surface != "whatsapp"
            or session is None
            or session.conversation_id != run.conversation_id
        ):
            logger.warning(
                "whatsapp_callback_ignored", extra={"bot_id": bot_id, "run_id": str(run_id)}
            )
            return
        text = await _latest_answer(db, run)
    if at is not None:
        # A status with no time of its own cannot say it is newer than the customer's message.
        await store.close(bot_id, chat_id, at=at)
    if not await store.hold_new(bot_id, chat_id, run_id=str(run_id)):
        return
    async with chat_lock(bot_id, chat_id):
        if await store.window(bot_id, chat_id, now=_now()) is not False:
            # The customer wrote since: the answer goes out as text, not as a preview.
            delivered = await _deliver_answers(bot_id, organization_id, chat_id, store)
            owing = [held for held in delivered if held.prompts_owed]
            if owing:
                await _offer_again(bot_id, organization_id, chat_id, owing, store)
            return
        token = await _bot_token(bot_id, organization_id)
        if token is not None:
            await whatsapp_adapter().send_held_preview(
                token,
                OutgoingMessage(platform_chat_id=chat_id, text=text, run_id=str(run_id)),
            )
