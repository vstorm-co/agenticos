"""The store behind WhatsApp's 24-hour window: each call is its own transaction (#2076).

The adapter and the inbound handler have no request session, and a hold has to be
committed before anything is sent, so every method opens a session of its own and
commits on exit. That is a second pooled connection while a caller may already hold
one, as Teams' `_ref` does (`teams.py`): callers must not wait on this store while
holding a lock the store's own transaction needs.

A hold or a claim takes the customer's row `FOR UPDATE` and reads the window again
inside that transaction, so it serializes with the webhook's `record_inbound`. No
Graph call is ever made while the lock is held.
"""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.whatsapp_customer import WhatsAppCustomer
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.whatsapp_templates import LateTemplate, stored_template
from app.services.channels.whatsapp_window import (
    CLAIM_LEASE,
    UndeliveredReason,
    closure_is_news,
    window_open,
)


@dataclass(frozen=True)
class Held:
    """A claimed held run: what is owed for it, and the row to settle afterwards."""

    id: UUID
    run_id: UUID
    answer: bool
    files: bool
    message_id: UUID | None = None
    """The saved answer this row owes; `None` for the run's prompts."""
    version: int = 1
    """The row's `hold_version` when it was claimed: a settlement is valid only while it still is."""
    prompts_owed: bool = False
    """Set by the delivery: the run still waits on prompts to offer again."""
    claimed_at: datetime | None = None
    """The claim this delivery holds; a settlement is valid only while the row still carries it."""


class WindowStore:
    """Reads and writes a WhatsApp customer's window; `bot_id` and `chat_id` are strings, as the adapter holds them."""

    def __init__(
        self, sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]] | None = None
    ) -> None:
        if sessions is None:
            from app.db.session import get_db_context

            sessions = get_db_context
        self._sessions = sessions

    async def _organization(self, db: AsyncSession, bot_id: str) -> UUID:
        from app.repositories import channel_bot_repo

        bot = await channel_bot_repo.get_for_inbound(db, UUID(bot_id))
        if bot is None:
            raise ChannelNotConfigured(
                "The WhatsApp bot no longer exists", details={"bot_id": bot_id}
            )
        return bot.organization_id

    @staticmethod
    async def _owed_message(
        db: AsyncSession, customer: WhatsAppCustomer, run_id: str, *, answer: bool
    ) -> UUID | None:
        """The run's latest saved answer as of now, for a hold of an answer; `None` for prompts.

        Each answer is held when it is refused, so the latest one saved is the one that
        was just refused. The row keeps its id and never "the latest" afterwards.
        """
        if not answer:
            return None
        from app.repositories import conversation_repo

        message = await conversation_repo.last_answer_message(
            db, UUID(run_id), organization_id=customer.organization_id
        )
        return message.id if message is not None else None

    async def window(self, bot_id: str, chat_id: str, *, now: datetime) -> bool | None:
        """Whether the window is open, or `None` when nothing is recorded for the customer."""
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            customer = await whatsapp_customer_repo.get(db, bot_id=UUID(bot_id), bsuid=chat_id)
            if customer is None:
                return None
            return window_open(
                last_inbound_at=customer.last_inbound_at,
                closed_at=customer.window_closed_at,
                now=now,
            )

    async def late_template(self, bot_id: str) -> LateTemplate | None:
        from app.repositories import channel_bot_repo

        async with self._sessions() as db:
            bot = await channel_bot_repo.get_for_inbound(db, UUID(bot_id))
            return stored_template(bot.whatsapp_late_template) if bot else None

    async def hold_unless_open(
        self, bot_id: str, chat_id: str, *, run_id: str, answer: bool, files: bool, now: datetime
    ) -> bool:
        """True when the window is open (nothing written); otherwise hold the run and return False."""
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            customer = await whatsapp_customer_repo.lock(
                db,
                organization_id=await self._organization(db, bot_id),
                bot_id=UUID(bot_id),
                bsuid=chat_id,
            )
            if window_open(
                last_inbound_at=customer.last_inbound_at,
                closed_at=customer.window_closed_at,
                now=now,
            ):
                return True
            await whatsapp_customer_repo.hold_run(
                db,
                customer=customer,
                run_id=UUID(run_id),
                answer=answer,
                files=files,
                message_id=await self._owed_message(db, customer, run_id, answer=answer),
            )
            return False

    async def hold(
        self, bot_id: str, chat_id: str, *, run_id: str, answer: bool, files: bool
    ) -> None:
        """Hold the run whatever the record says: Meta has just refused the send as outside the window."""
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            customer = await whatsapp_customer_repo.lock(
                db,
                organization_id=await self._organization(db, bot_id),
                bot_id=UUID(bot_id),
                bsuid=chat_id,
            )
            await whatsapp_customer_repo.hold_run(
                db,
                customer=customer,
                run_id=UUID(run_id),
                answer=answer,
                files=files,
                message_id=await self._owed_message(db, customer, run_id, answer=answer),
            )

    async def hold_new(self, bot_id: str, chat_id: str, *, run_id: str) -> bool:
        """Hold a run's answer whatever the window; True only when this call created the row."""
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            customer = await whatsapp_customer_repo.lock(
                db,
                organization_id=await self._organization(db, bot_id),
                bot_id=UUID(bot_id),
                bsuid=chat_id,
            )
            return await whatsapp_customer_repo.hold_run(
                db,
                customer=customer,
                run_id=UUID(run_id),
                answer=True,
                files=False,
                message_id=await self._owed_message(db, customer, run_id, answer=True),
            )

    async def close(self, bot_id: str, chat_id: str, *, at: datetime) -> bool:
        """Record that Meta refused a send as outside the window; True when that was news."""
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            customer = await whatsapp_customer_repo.lock(
                db,
                organization_id=await self._organization(db, bot_id),
                bot_id=UUID(bot_id),
                bsuid=chat_id,
            )
            if not closure_is_news(
                last_inbound_at=customer.last_inbound_at,
                closed_at=customer.window_closed_at,
                at=at,
            ):
                return False
            await whatsapp_customer_repo.update(
                db, customer=customer, update_data={"window_closed_at": at}
            )
            return True

    async def has_held(self, bot_id: str, chat_id: str, *, now: datetime) -> bool:
        """Whether a held run could be claimed now; takes no lock.

        A row under a live claim that owes only prompts is spanning the routed turn,
        so a message that arrives meanwhile routes at once. One still owing an answer
        or files is a send under way: the message waits, so it is routed after it.
        """
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            return await whatsapp_customer_repo.has_held(
                db, bot_id=UUID(bot_id), bsuid=chat_id, claimable_before=now - CLAIM_LEASE
            )

    async def claim_held(self, bot_id: str, chat_id: str, *, now: datetime) -> list[Held]:
        """Take the customer's unclaimed held runs, oldest first; a claim past its lease can be taken again.

        A holder whose lease lapsed may already have sent what the row owes. The
        claim fence keeps the newer holder's row from being settled by the older
        one; it cannot unsend.
        """
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            customer = await whatsapp_customer_repo.lock(
                db,
                organization_id=await self._organization(db, bot_id),
                bot_id=UUID(bot_id),
                bsuid=chat_id,
            )
            rows = await whatsapp_customer_repo.held_runs(
                db, customer=customer, claimable_before=now - CLAIM_LEASE
            )
            for row in rows:
                await whatsapp_customer_repo.update_held(
                    db, held=row, update_data={"claimed_at": now}
                )
            return [
                Held(
                    id=row.id,
                    run_id=row.run_id,
                    answer=row.held_answer,
                    files=row.held_files,
                    message_id=row.message_id,
                    version=row.hold_version,
                    claimed_at=row.claimed_at,
                )
                for row in rows
            ]

    async def answer_sent(self, held: Held, *, prompts_owed: bool) -> None:
        """The run's answer reached the customer: keep or drop the row, then clear its reason if nothing else is owed.

        With `prompts_owed` the row stays, claimed, for the prompts still to be
        offered again; otherwise it is deleted. A row held again since the claim
        (`hold_version` moved) is left as it is with its claim given back, and its
        reason stays: something said the answer did not arrive, and the next
        delivery sends it again. A claim since taken over settles nothing.
        """
        from app.repositories import agent_run_repo, whatsapp_customer_repo

        async with self._sessions() as db:
            row = await whatsapp_customer_repo.lock_held(db, held_id=held.id)
            if row is None or row.claimed_at != held.claimed_at:
                return
            if row.hold_version != held.version:
                await whatsapp_customer_repo.update_held(
                    db, held=row, update_data={"claimed_at": None}
                )
                return
            if prompts_owed:
                await whatsapp_customer_repo.update_held(
                    db, held=row, update_data={"held_answer": False, "held_files": False}
                )
            else:
                await whatsapp_customer_repo.delete_held(db, held_id=row.id)
            # The run page's reason stands while another answer of the run is still owed.
            if not await whatsapp_customer_repo.run_owes_answer(db, run_id=row.run_id):
                await agent_run_repo.mark_undelivered(
                    db, run_id=row.run_id, organization_id=row.organization_id, reason=None
                )

    async def done(self, held: Held) -> None:
        """The row's remaining duty is over: drop it, unless the run was held again since the claim.

        A claim since taken over settles nothing.
        """
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            row = await whatsapp_customer_repo.lock_held(db, held_id=held.id)
            if row is None or row.claimed_at != held.claimed_at:
                return
            if row.hold_version != held.version:
                await whatsapp_customer_repo.update_held(
                    db, held=row, update_data={"claimed_at": None}
                )
            else:
                await whatsapp_customer_repo.delete_held(db, held_id=row.id)

    async def release(self, held: Held) -> None:
        """Give the claim back so the next delivery can take the row; flags and reason are untouched.

        Only the holder of the row's current claim gives it back.
        """
        from app.repositories import whatsapp_customer_repo

        async with self._sessions() as db:
            row = await whatsapp_customer_repo.lock_held(db, held_id=held.id)
            if row is not None and row.claimed_at == held.claimed_at:
                await whatsapp_customer_repo.update_held(
                    db, held=row, update_data={"claimed_at": None}
                )

    async def record_undelivered(
        self, bot_id: str, run_id: str, reason: UndeliveredReason | None
    ) -> None:
        """Say why a run's answer has not reached the customer, within the bot's organization."""
        from app.repositories import agent_run_repo

        async with self._sessions() as db:
            await agent_run_repo.mark_undelivered(
                db,
                run_id=UUID(run_id),
                organization_id=await self._organization(db, bot_id),
                reason=reason,
            )
