"""The WhatsApp customer record and the store over it, against Postgres (#2076)."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_link_request import ChannelLinkRequest
from app.db.models.channel_session import ChannelSession
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.whatsapp_customer import WhatsAppCustomer, WhatsAppHeldRun
from app.repositories import agent_run_repo, conversation_repo, whatsapp_customer_repo
from app.services.channels.whatsapp_customers import Held, WindowStore
from app.services.channels.whatsapp_payload import platform_user_id_for
from app.services.channels.whatsapp_templates import LateTemplate, to_stored
from app.services.channels.whatsapp_window import CLAIM_LEASE

pytestmark = pytest.mark.anyio

T1 = datetime(2026, 11, 4, 10, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)
T3 = T1 + timedelta(hours=2)
BSUID = "US.111"


@pytest.fixture
def sessions(engine: AsyncEngine) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """Sessions that commit for real, for the code under test that opens its own."""
    factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def open_session() -> AsyncGenerator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    return open_session


async def _estate(db: AsyncSession) -> tuple[Organization, ChannelBot, User, Agent]:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    bot = ChannelBot(
        organization_id=org.id,
        platform="whatsapp",
        name="Support",
        token_encrypted="x",
        whatsapp_phone_number_id="123",
        whatsapp_account_id="456",
    )
    agent = Agent(organization_id=org.id, slug=f"a-{uuid.uuid4().hex[:6]}", name="A", draft_spec={})
    db.add_all([bot, agent])
    await db.flush()
    return org, bot, user, agent


async def _run(db: AsyncSession, org: Organization, user: User, agent: Agent) -> AgentRun:
    return await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=user.id,
        conversation_id=None,
        surface="whatsapp",
        model_label="m",
        provider="openai",
        secret_id=None,
        started_at=datetime.now(UTC),
    )


async def _customer(db: AsyncSession, org: Organization, bot: ChannelBot) -> WhatsAppCustomer:
    return await whatsapp_customer_repo.lock(db, organization_id=org.id, bot_id=bot.id, bsuid=BSUID)


async def test_a_full_length_business_scoped_id_fits_every_column_that_holds_it(
    db: AsyncSession,
) -> None:
    org, bot, _, _ = await _estate(db)
    longest = "US." + "a" * 128
    namespaced = platform_user_id_for(org.id, longest)
    assert (len(longest), len(namespaced)) == (131, 168)

    await whatsapp_customer_repo.record_inbound(
        db, organization_id=org.id, bot_id=bot.id, bsuid=longest, sent_at=T1
    )
    identity = ChannelIdentity(platform="whatsapp", platform_user_id=namespaced)
    db.add(identity)
    await db.flush()
    db.add_all(
        [
            ChannelSession(bot_id=bot.id, identity_id=identity.id, platform_chat_id=longest),
            ChannelLinkRequest(
                token=uuid.uuid4().hex,
                platform="whatsapp",
                platform_user_id=namespaced,
                expires_at=T2,
            ),
        ]
    )
    await db.flush()

    assert (await db.scalar(select(WhatsAppCustomer.bsuid))) == longest
    assert (await db.scalar(select(ChannelIdentity.platform_user_id))) == namespaced
    assert (await db.scalar(select(ChannelSession.platform_chat_id))) == longest
    assert (await db.scalar(select(ChannelLinkRequest.platform_user_id))) == namespaced


async def test_the_latest_message_time_is_kept(db: AsyncSession) -> None:
    org, bot, _, _ = await _estate(db)

    async def record(at: datetime) -> datetime | None:
        await whatsapp_customer_repo.record_inbound(
            db, organization_id=org.id, bot_id=bot.id, bsuid=BSUID, sent_at=at
        )
        row = await whatsapp_customer_repo.get(db, bot_id=bot.id, bsuid=BSUID)
        assert row is not None
        await db.refresh(row)
        return row.last_inbound_at

    assert await record(T2) == T2
    assert await record(T1) == T2
    assert await record(T3) == T3


async def test_one_record_per_bot_and_customer(db: AsyncSession) -> None:
    org, bot, _, _ = await _estate(db)
    db.add(WhatsAppCustomer(organization_id=org.id, bot_id=bot.id, bsuid=BSUID))
    await db.flush()
    async with db.begin_nested():
        db.add(WhatsAppCustomer(organization_id=org.id, bot_id=bot.id, bsuid=BSUID))
        with pytest.raises(IntegrityError):
            await db.flush()


async def test_deleting_the_bot_removes_its_customers_and_their_held_runs(
    db: AsyncSession,
) -> None:
    org, bot, user, agent = await _estate(db)
    run = await _run(db, org, user, agent)
    customer = await _customer(db, org, bot)
    await whatsapp_customer_repo.hold_run(
        db, customer=customer, run_id=run.id, answer=True, files=False
    )
    await db.delete(bot)
    await db.flush()
    db.expunge_all()
    assert (await db.execute(select(WhatsAppCustomer))).first() is None
    assert (await db.execute(select(WhatsAppHeldRun))).first() is None


async def test_deleting_a_held_run_removes_its_row(db: AsyncSession) -> None:
    org, bot, user, agent = await _estate(db)
    run = await _run(db, org, user, agent)
    customer = await _customer(db, org, bot)
    await whatsapp_customer_repo.hold_run(
        db, customer=customer, run_id=run.id, answer=True, files=False
    )
    await db.delete(run)
    await db.flush()
    db.expunge_all()
    assert (await db.execute(select(WhatsAppHeldRun))).first() is None
    assert await whatsapp_customer_repo.get(db, bot_id=bot.id, bsuid=BSUID) is not None


async def test_lock_creates_a_bare_record_for_a_customer_who_never_wrote(
    db: AsyncSession,
) -> None:
    org, bot, _, _ = await _estate(db)
    customer = await _customer(db, org, bot)
    assert customer.last_inbound_at is None
    assert customer.window_closed_at is None
    assert (await _customer(db, org, bot)).id == customer.id


async def test_holding_a_run_twice_keeps_one_row_and_ors_what_it_owes(db: AsyncSession) -> None:
    org, bot, user, agent = await _estate(db)
    run = await _run(db, org, user, agent)
    customer = await _customer(db, org, bot)
    assert await whatsapp_customer_repo.hold_run(
        db, customer=customer, run_id=run.id, answer=True, files=False
    )
    assert not await whatsapp_customer_repo.hold_run(
        db, customer=customer, run_id=run.id, answer=False, files=True
    )
    [row] = await whatsapp_customer_repo.held_runs(db, customer=customer, claimable_before=T3)
    assert row.held_answer
    assert row.held_files


async def test_the_repository_updates_and_reads_what_it_holds(db: AsyncSession) -> None:
    org, bot, user, agent = await _estate(db)
    run = await _run(db, org, user, agent)
    customer = await _customer(db, org, bot)
    await whatsapp_customer_repo.update(db, customer=customer, update_data={"window_closed_at": T1})
    assert customer.window_closed_at == T1
    assert not await whatsapp_customer_repo.has_held(
        db, bot_id=bot.id, bsuid=BSUID, claimable_before=T3
    )
    await whatsapp_customer_repo.hold_run(
        db, customer=customer, run_id=run.id, answer=True, files=False
    )
    assert await whatsapp_customer_repo.has_held(
        db, bot_id=bot.id, bsuid=BSUID, claimable_before=T3
    )
    [row] = await whatsapp_customer_repo.held_runs(db, customer=customer, claimable_before=T3)
    await whatsapp_customer_repo.update_held(db, held=row, update_data={"claimed_at": T1})
    assert await whatsapp_customer_repo.held_runs(db, customer=customer, claimable_before=T1) == []
    await whatsapp_customer_repo.delete_held(db, held_id=row.id)
    assert not await whatsapp_customer_repo.has_held(
        db, bot_id=bot.id, bsuid=BSUID, claimable_before=T3
    )


@pytest.mark.security
async def test_an_undelivered_reason_is_written_only_within_the_organization(
    db: AsyncSession,
) -> None:
    org, _, user, agent = await _estate(db)
    run = await _run(db, org, user, agent)
    await agent_run_repo.mark_undelivered(
        db, run_id=run.id, organization_id=uuid.uuid4(), reason="window_no_template"
    )
    await db.refresh(run)
    assert run.undelivered_reason is None
    await agent_run_repo.mark_undelivered(
        db, run_id=run.id, organization_id=org.id, reason="window_no_template"
    )
    await db.refresh(run)
    assert run.undelivered_reason == "window_no_template"
    await agent_run_repo.mark_undelivered(db, run_id=run.id, organization_id=org.id, reason=None)
    await db.refresh(run)
    assert run.undelivered_reason is None


class TestTheStore:
    """The store opens its own sessions, so these tests commit for real."""

    @pytest.fixture
    async def estate(
        self, sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    ) -> tuple[Organization, ChannelBot, list[uuid.UUID]]:
        async with sessions() as db:
            org, bot, user, agent = await _estate(db)
            runs = [(await _run(db, org, user, agent)).id for _ in range(2)]
        return org, bot, runs

    async def _record(
        self,
        sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        org: Organization,
        bot: ChannelBot,
        at: datetime,
    ) -> None:
        async with sessions() as db:
            await whatsapp_customer_repo.record_inbound(
                db, organization_id=org.id, bot_id=bot.id, bsuid=BSUID, sent_at=at
            )

    async def _last_inbound(
        self, sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]], bot: ChannelBot
    ) -> datetime | None:
        async with sessions() as db:
            row = await whatsapp_customer_repo.get(db, bot_id=bot.id, bsuid=BSUID)
            assert row is not None
            return row.last_inbound_at

    async def test_a_message_being_recorded_waits_for_a_hold(self, sessions, estate) -> None:
        org, bot, runs = estate
        await self._record(sessions, org, bot, T1)
        async with sessions() as holder:
            customer = await whatsapp_customer_repo.lock(
                holder, organization_id=org.id, bot_id=bot.id, bsuid=BSUID
            )
            recording = asyncio.create_task(self._record(sessions, org, bot, T2))
            await asyncio.sleep(0.2)
            assert not recording.done()
            await whatsapp_customer_repo.hold_run(
                holder, customer=customer, run_id=runs[0], answer=True, files=False
            )
        await asyncio.wait_for(recording, timeout=5)
        assert await self._last_inbound(sessions, bot) == T2

    async def test_a_hold_on_a_closed_window_is_kept_and_an_open_one_is_refused(
        self, sessions, estate
    ) -> None:
        org, bot, runs = estate
        store = WindowStore(sessions)
        now = T1 + timedelta(hours=1)
        await self._record(sessions, org, bot, T1)
        assert await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=now
        )
        assert not await store.has_held(str(bot.id), BSUID, now=T3)
        late = T1 + timedelta(hours=30)
        assert not await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=late
        )
        assert await store.has_held(str(bot.id), BSUID, now=T3)

    async def test_a_hold_for_a_customer_with_no_record_creates_one_and_holds(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        assert await store.window(str(bot.id), BSUID, now=T3) is None
        assert not await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=True, now=T3
        )
        assert await store.window(str(bot.id), BSUID, now=T3) is False

    async def test_two_runs_are_held_side_by_side(self, sessions, estate) -> None:
        org, bot, runs = estate
        store = WindowStore(sessions)
        for run in runs:
            await store.hold_unless_open(
                str(bot.id), BSUID, run_id=str(run), answer=True, files=False, now=T3
            )
        claimed = await store.claim_held(str(bot.id), BSUID, now=T3)
        assert [held.run_id for held in claimed] == runs
        assert all(isinstance(held, Held) and held.answer for held in claimed)

    async def test_a_prompt_hold_never_clears_an_owed_answer(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        for answer in (True, False):
            await store.hold_unless_open(
                str(bot.id), BSUID, run_id=str(runs[0]), answer=answer, files=False, now=T3
            )
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        assert held.answer

    async def test_held_runs_are_claimed_once(self, sessions, estate) -> None:
        org, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=T3
        )
        async with sessions() as third:
            await whatsapp_customer_repo.lock(
                third, organization_id=org.id, bot_id=bot.id, bsuid=BSUID
            )
            claims = [
                asyncio.create_task(store.claim_held(str(bot.id), BSUID, now=T3)) for _ in range(2)
            ]
            await asyncio.sleep(0.2)
            assert not any(claim.done() for claim in claims)
        results = await asyncio.wait_for(asyncio.gather(*claims), timeout=5)
        assert sorted(len(result) for result in results) == [0, 1]

    async def test_a_claim_older_than_the_lease_is_claimed_again(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=T3
        )
        assert len(await store.claim_held(str(bot.id), BSUID, now=T3)) == 1
        assert await store.claim_held(str(bot.id), BSUID, now=T3 + CLAIM_LEASE) == []
        later = T3 + CLAIM_LEASE + timedelta(seconds=1)
        assert len(await store.claim_held(str(bot.id), BSUID, now=later)) == 1

    async def _taken_over(self, sessions, estate) -> tuple[Held, Held]:
        """A claim at T3 that lapsed, and the second holder that took the row over."""
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=T3
        )
        [first] = await store.claim_held(str(bot.id), BSUID, now=T3)
        later = T3 + CLAIM_LEASE + timedelta(seconds=1)
        [second] = await store.claim_held(str(bot.id), BSUID, now=later)
        assert (first.claimed_at, second.claimed_at) == (T3, later)
        return first, second

    @pytest.mark.parametrize("settle", ["release", "done", "answer_sent"])
    async def test_a_holder_whose_claim_was_taken_over_cannot_settle_the_newer_claim(
        self, sessions, estate, settle: str
    ) -> None:
        store = WindowStore(sessions)
        first, second = await self._taken_over(sessions, estate)
        if settle == "answer_sent":
            await store.answer_sent(first, prompts_owed=False)
        else:
            await getattr(store, settle)(first)

        row = await self._held_row(sessions)
        assert (row.claimed_at, row.held_answer) == (second.claimed_at, True)
        await store.done(second)
        async with sessions() as db:
            assert (await db.execute(select(WhatsAppHeldRun))).first() is None

    async def test_a_fenced_answer_sent_leaves_the_runs_reason(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.record_undelivered(str(bot.id), str(runs[0]), "window_no_template")
        first, _ = await self._taken_over(sessions, estate)
        await store.answer_sent(first, prompts_owed=False)

        assert await self._reason(sessions, runs[0]) == "window_no_template"

    async def test_the_fence_decides_before_a_hold_that_moved_the_version(
        self, sessions, estate
    ) -> None:
        first, second = await self._taken_over(sessions, estate)
        await self._rehold(sessions, estate, first.run_id, answer=True, files=True)
        store = WindowStore(sessions)
        await store.done(first)
        await store.answer_sent(first, prompts_owed=False)

        row = await self._held_row(sessions)
        assert (row.claimed_at, row.held_files) == (second.claimed_at, True)

    async def test_a_claim_given_back_and_taken_again_refuses_the_old_holder(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=T3
        )
        [first] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.release(first)
        again = T3 + timedelta(minutes=5)
        [second] = await store.claim_held(str(bot.id), BSUID, now=again)
        await store.done(first)

        assert (await self._held_row(sessions)).claimed_at == second.claimed_at == again

    async def test_the_reason_is_cleared_only_when_the_answer_was_sent(
        self, sessions, estate
    ) -> None:
        org, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=T3
        )
        await store.record_undelivered(str(bot.id), str(runs[0]), "window_no_template")
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.release(held)
        assert await self._reason(sessions, runs[0]) == "window_no_template"
        [second] = await store.claim_held(str(bot.id), BSUID, now=T3 + timedelta(minutes=1))
        await store.answer_sent(second, prompts_owed=False)
        assert await self._reason(sessions, runs[0]) is None
        assert not await store.has_held(str(bot.id), BSUID, now=T3)

    async def test_an_answer_sent_with_prompts_owed_keeps_the_row_until_done(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=True, now=T3
        )
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.answer_sent(held, prompts_owed=True)
        assert not await store.has_held(str(bot.id), BSUID, now=T3)
        assert await store.claim_held(str(bot.id), BSUID, now=T3) == []
        async with sessions() as db:
            row = (await db.execute(select(WhatsAppHeldRun))).scalar_one()
            assert (row.held_answer, row.held_files, row.claimed_at) == (False, False, T3)
        await store.done(held)
        assert not await store.has_held(str(bot.id), BSUID, now=T3)

    async def _held_row(self, sessions) -> WhatsAppHeldRun:
        async with sessions() as db:
            return (await db.execute(select(WhatsAppHeldRun))).scalar_one()

    async def _rehold(
        self, sessions, estate, run_id, *, answer: bool, files: bool, notice: str | None = None
    ) -> None:
        """A hold from a third session, as the late path or a reclaim makes it."""
        org, bot, _ = estate
        async with sessions() as third:
            await whatsapp_customer_repo.hold_run(
                third,
                customer=await whatsapp_customer_repo.lock(
                    third, organization_id=org.id, bot_id=bot.id, bsuid=BSUID
                ),
                run_id=run_id,
                answer=answer,
                files=files,
                notice=notice,
            )

    async def test_a_hold_merged_after_the_claim_survives_done(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=False, files=False, now=T3
        )
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await self._rehold(sessions, estate, runs[0], answer=True, files=True)
        await store.done(held)

        row = await self._held_row(sessions)
        assert (row.held_answer, row.held_files, row.claimed_at) == (True, True, None)
        assert len(await store.claim_held(str(bot.id), BSUID, now=T3)) == 1

    async def test_a_hold_merged_after_an_answer_sent_survives_the_prompts_done(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=T3
        )
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.answer_sent(held, prompts_owed=True)
        await self._rehold(sessions, estate, runs[0], answer=True, files=False)
        await store.done(held)

        row = await self._held_row(sessions)
        assert (row.held_answer, row.claimed_at) == (True, None)

    async def test_a_rehold_with_identical_flags_during_the_send_survives(
        self, sessions, estate
    ) -> None:
        """The adapter's late path holds the run again, with what the claim carried, while it sends."""
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=T3
        )
        await store.record_undelivered(str(bot.id), str(runs[0]), "window_template_failed")
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await self._rehold(sessions, estate, runs[0], answer=True, files=False)
        await store.answer_sent(held, prompts_owed=False)

        row = await self._held_row(sessions)
        assert (row.held_answer, row.claimed_at) == (True, None)
        assert await self._reason(sessions, runs[0]) == "window_template_failed"

    async def test_a_hold_merged_during_an_answer_sent_keeps_the_row_and_the_reason(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=T3
        )
        await store.record_undelivered(str(bot.id), str(runs[0]), "window_no_template")
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await self._rehold(sessions, estate, runs[0], answer=False, files=True)
        await store.answer_sent(held, prompts_owed=True)

        row = await self._held_row(sessions)
        assert (row.held_answer, row.held_files, row.claimed_at) == (True, True, None)
        assert await self._reason(sessions, runs[0]) == "window_no_template"

    async def test_an_unchanged_row_is_deleted_by_done(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=False, files=False, now=T3
        )
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.done(held)
        assert not await store.has_held(str(bot.id), BSUID, now=T3)

    async def test_a_live_claim_still_owing_an_answer_or_files_is_something_to_wait_for(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=False, files=True, now=T3
        )
        await store.claim_held(str(bot.id), BSUID, now=T3)
        assert await store.has_held(str(bot.id), BSUID, now=T3)

    async def test_a_live_claim_owing_only_prompts_is_not_something_to_wait_for(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=False, files=False, now=T3
        )
        assert await store.has_held(str(bot.id), BSUID, now=T3)
        await store.claim_held(str(bot.id), BSUID, now=T3)
        assert not await store.has_held(str(bot.id), BSUID, now=T3)
        assert await store.has_held(str(bot.id), BSUID, now=T3 + CLAIM_LEASE + timedelta(seconds=1))

    async def test_a_settlement_covering_everything_still_clears_the_row(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=True, now=T3
        )
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.answer_sent(held, prompts_owed=False)
        assert not await store.has_held(str(bot.id), BSUID, now=T3)

    async def test_hold_new_is_true_once_per_run(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        first = await store.hold_new(str(bot.id), BSUID, run_id=str(runs[0]))
        again = await store.hold_new(str(bot.id), BSUID, run_id=str(runs[0]))
        other = await store.hold_new(str(bot.id), BSUID, run_id=str(runs[1]))
        assert (first, again, other) == (True, False, True)

    async def test_hold_holds_whatever_the_record_says(self, sessions, estate) -> None:
        org, bot, runs = estate
        store = WindowStore(sessions)
        await self._record(sessions, org, bot, T3)
        assert await store.window(str(bot.id), BSUID, now=T3) is True
        await store.hold(str(bot.id), BSUID, run_id=str(runs[0]), answer=False, files=False)
        await store.hold(str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=True)
        async with sessions() as db:
            row = (await db.execute(select(WhatsAppHeldRun))).scalar_one()
            assert (row.held_answer, row.held_files) == (True, True)

    async def test_a_closure_is_news_once_per_message(self, sessions, estate) -> None:
        org, bot, _ = estate
        store = WindowStore(sessions)
        await self._record(sessions, org, bot, T1)
        first = await store.close(str(bot.id), BSUID, at=T1 + timedelta(minutes=1))
        second = await store.close(str(bot.id), BSUID, at=T1 + timedelta(minutes=2))
        assert (first, second) == (True, False)
        assert await store.window(str(bot.id), BSUID, now=T1 + timedelta(minutes=3)) is False
        await self._record(sessions, org, bot, T2)
        stale = await store.close(str(bot.id), BSUID, at=T1 + timedelta(minutes=30))
        assert not stale
        assert await store.window(str(bot.id), BSUID, now=T2 + timedelta(minutes=1)) is True

    async def test_a_message_in_the_second_of_a_closure_reopens_the_window(
        self, sessions, estate
    ) -> None:
        org, bot, _ = estate
        store = WindowStore(sessions)
        await self._record(sessions, org, bot, T1)
        assert await store.close(str(bot.id), BSUID, at=T2)
        assert await store.window(str(bot.id), BSUID, now=T2 + timedelta(minutes=1)) is False
        await self._record(sessions, org, bot, T2)
        assert await store.window(str(bot.id), BSUID, now=T2 + timedelta(minutes=1)) is True
        assert await store.close(str(bot.id), BSUID, at=T2 + timedelta(minutes=2))

    async def test_no_record_reads_as_none(self, sessions, estate) -> None:
        _, bot, _ = estate
        store = WindowStore(sessions)
        assert await store.window(str(bot.id), BSUID, now=T3) is None
        assert not await store.has_held(str(bot.id), BSUID, now=T3)

    async def test_the_late_template_reads_from_the_bot(self, sessions, estate) -> None:
        _, bot, _ = estate
        store = WindowStore(sessions)
        assert await store.late_template(str(bot.id)) is None
        template = LateTemplate(name="late", language="en_US", body="Hi: {{1}} Bye.")
        async with sessions() as db:
            row = await db.get(ChannelBot, bot.id)
            assert row is not None
            row.whatsapp_late_template = to_stored(template)
        assert await store.late_template(str(bot.id)) == template
        async with sessions() as db:
            row = await db.get(ChannelBot, bot.id)
            assert row is not None
            row.whatsapp_late_template = {"name": 1}
        assert await store.late_template(str(bot.id)) is None
        assert await store.late_template(str(uuid.uuid4())) is None

    @pytest.mark.security
    async def test_the_reason_is_scoped_to_the_bots_organization(self, sessions, estate) -> None:
        _, bot, runs = estate
        async with sessions() as db:
            other, _, other_user, other_agent = await _estate(db)
            foreign = (await _run(db, other, other_user, other_agent)).id
        store = WindowStore(sessions)
        await store.record_undelivered(str(bot.id), str(foreign), "window_no_template")
        assert await self._reason(sessions, foreign) is None

    async def _notice_hold(self, store: WindowStore, bot, run_id, key: str) -> None:
        await store.hold(
            str(bot.id), BSUID, run_id=str(run_id), answer=False, files=False, notice=key
        )

    async def test_a_notice_is_held_on_the_runs_prompts_row_and_owes_no_answer(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=False, files=False, now=T3
        )
        await self._notice_hold(store, bot, runs[0], "stopped")

        row = await self._held_row(sessions)
        assert (row.held_notice, row.held_answer, row.held_files, row.message_id) == (
            "stopped",
            False,
            False,
            None,
        )
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        assert (held.notice, held.answer, held.files) == ("stopped", False, False)

    async def test_a_prompts_hold_after_a_notice_keeps_the_notice(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await self._notice_hold(store, bot, runs[0], "stopped")
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=False, files=False, now=T3
        )

        assert (await self._held_row(sessions)).held_notice == "stopped"

    async def test_a_second_notice_replaces_the_first(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await self._notice_hold(store, bot, runs[0], "expired")
        await self._notice_hold(store, bot, runs[0], "stopped")

        assert (await self._held_row(sessions)).held_notice == "stopped"

    async def test_a_notice_held_during_a_claim_survives_done(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=False, files=False, now=T3
        )
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await self._rehold(sessions, estate, runs[0], answer=False, files=False, notice="stopped")
        await store.done(held)

        row = await self._held_row(sessions)
        assert (row.held_notice, row.claimed_at) == ("stopped", None)

    async def test_a_notice_only_row_is_something_to_wait_for_and_to_claim(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await self._notice_hold(store, bot, runs[0], "stopped")
        assert await store.has_held(str(bot.id), BSUID, now=T3)
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        assert await store.has_held(str(bot.id), BSUID, now=T3)
        await store.notice_sent(held)
        assert not await store.has_held(str(bot.id), BSUID, now=T3)

    async def test_a_notice_sent_clears_the_notice_and_keeps_the_prompts_claim(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.record_undelivered(str(bot.id), str(runs[0]), "window_no_template")
        await self._notice_hold(store, bot, runs[0], "stopped")
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.notice_sent(held)

        row = await self._held_row(sessions)
        assert (row.held_notice, row.claimed_at) == (None, T3)
        assert await self._reason(sessions, runs[0]) == "window_no_template"

    async def test_a_notice_sent_after_a_hold_moved_the_version_gives_the_claim_back(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await self._notice_hold(store, bot, runs[0], "stopped")
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await self._rehold(sessions, estate, runs[0], answer=False, files=False, notice="stopped")
        await store.notice_sent(held)

        row = await self._held_row(sessions)
        assert (row.held_notice, row.claimed_at) == ("stopped", None)

    async def test_a_holder_whose_claim_was_taken_over_cannot_settle_the_notice(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await self._notice_hold(store, bot, runs[0], "stopped")
        [first] = await store.claim_held(str(bot.id), BSUID, now=T3)
        later = T3 + CLAIM_LEASE + timedelta(seconds=1)
        [second] = await store.claim_held(str(bot.id), BSUID, now=later)
        await store.notice_sent(first)

        row = await self._held_row(sessions)
        assert (row.held_notice, row.claimed_at) == ("stopped", second.claimed_at)

    async def test_an_answer_settled_to_keep_the_notice_leaves_a_notice_only_row(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.record_undelivered(str(bot.id), str(runs[0]), "window_no_template")
        await store.hold(str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=True)
        await self._notice_hold(store, bot, runs[0], "stopped")
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.answer_sent(held, prompts_owed=False, keep_notice=True)

        row = await self._held_row(sessions)
        assert (row.held_answer, row.held_files, row.held_notice, row.claimed_at) == (
            False,
            False,
            "stopped",
            T3,
        )
        assert await self._reason(sessions, runs[0]) is None
        await store.release(held)
        [again] = await store.claim_held(str(bot.id), BSUID, now=T3)
        assert (again.answer, again.notice) == (False, "stopped")

    async def test_an_answer_sent_with_prompts_owed_clears_the_notice(
        self, sessions, estate
    ) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        await store.hold(str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False)
        await self._notice_hold(store, bot, runs[0], "stopped")
        async with sessions() as db:
            rows = (await db.execute(select(WhatsAppHeldRun))).scalars().all()
            assert len(rows) == 1 and rows[0].held_answer and rows[0].held_notice == "stopped"
        [held] = await store.claim_held(str(bot.id), BSUID, now=T3)
        await store.answer_sent(held, prompts_owed=True)

        row = await self._held_row(sessions)
        assert (row.held_answer, row.held_notice, row.claimed_at) == (False, None, T3)

    async def _reason(
        self, sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]], run_id: uuid.UUID
    ) -> str | None:
        async with sessions() as db:
            row = await db.get(AgentRun, run_id)
            assert row is not None
            await db.refresh(row)
            return row.undelivered_reason


class TestEachOwedAnswerIsItsOwnRow:
    """A run held twice owes two answers, and each row names the saved message it owes."""

    @pytest.fixture
    async def estate(self, sessions):
        async with sessions() as db:
            org, bot, user, agent = await _estate(db)
            run = await _run(db, org, user, agent)
            conversation = Conversation(user_id=user.id, organization_id=org.id)
            db.add(conversation)
            await db.flush()
            run.conversation_id = conversation.id
            return org, bot, run.id, conversation.id

    async def _say(self, sessions, estate, text: str, *, role: str = "assistant") -> uuid.UUID:
        _, _, run_id, conversation_id = estate
        async with sessions() as db:
            message = await conversation_repo.create_message(
                db, conversation_id=conversation_id, role=role, content=text, run_id=run_id
            )
            return message.id

    async def _rows(self, sessions) -> list[WhatsAppHeldRun]:
        async with sessions() as db:
            result = await db.execute(
                select(WhatsAppHeldRun).order_by(WhatsAppHeldRun.created_at, WhatsAppHeldRun.id)
            )
            return list(result.scalars().all())

    async def _hold(self, store, estate, **flags) -> None:
        _, bot, run_id, _ = estate
        await store.hold(str(bot.id), BSUID, run_id=str(run_id), **{"files": False, **flags})

    async def test_two_late_answers_of_one_run_are_two_rows_pointing_at_their_messages(
        self, sessions, estate
    ) -> None:
        _, bot, _, _ = estate
        store = WindowStore(sessions)
        first = await self._say(sessions, estate, "first")
        await self._hold(store, estate, answer=True)
        second = await self._say(sessions, estate, "second")
        await self._hold(store, estate, answer=True)

        claimed = await store.claim_held(str(bot.id), BSUID, now=T3)

        assert [held.message_id for held in claimed] == [first, second]
        assert all(held.answer for held in claimed)

    async def test_the_reason_stays_while_another_answer_of_the_run_is_owed(
        self, sessions, estate
    ) -> None:
        _, bot, run_id, _ = estate
        store = WindowStore(sessions)
        await self._say(sessions, estate, "first")
        await self._hold(store, estate, answer=True)
        await self._say(sessions, estate, "second")
        await self._hold(store, estate, answer=True)
        await store.record_undelivered(str(bot.id), str(run_id), "window_no_template")
        first, second = await store.claim_held(str(bot.id), BSUID, now=T3)

        await store.answer_sent(first, prompts_owed=False)
        async with sessions() as db:
            still = await db.scalar(
                select(AgentRun.undelivered_reason).where(AgentRun.id == run_id)
            )
        assert still == "window_no_template"

        await store.answer_sent(second, prompts_owed=False)
        async with sessions() as db:
            cleared = await db.scalar(
                select(AgentRun.undelivered_reason).where(AgentRun.id == run_id)
            )
        assert cleared is None

    async def test_holding_the_same_answer_again_is_one_row_with_a_newer_version(
        self, sessions, estate
    ) -> None:
        store = WindowStore(sessions)
        message = await self._say(sessions, estate, "only")
        await self._hold(store, estate, answer=True)
        await self._hold(store, estate, answer=True)

        [row] = await self._rows(sessions)
        assert (row.message_id, row.hold_version) == (message, 2)

    async def test_the_prompts_of_a_run_are_their_own_row_beside_its_answers(
        self, sessions, estate
    ) -> None:
        _, bot, _, _ = estate
        store = WindowStore(sessions)
        message = await self._say(sessions, estate, "an answer")
        await self._hold(store, estate, answer=True)
        await self._hold(store, estate, answer=False)
        await self._hold(store, estate, answer=False)

        rows = await self._rows(sessions)

        assert sorted((row.message_id is None, row.held_answer) for row in rows) == [
            (False, True),
            (True, False),
        ]
        assert {row.message_id for row in rows} == {message, None}

    async def test_a_user_message_is_never_the_one_owed(self, sessions, estate) -> None:
        await self._say(sessions, estate, "a question", role="user")
        await self._hold(WindowStore(sessions), estate, answer=True)

        [row] = await self._rows(sessions)
        assert row.message_id is None

    async def test_deleting_the_message_removes_the_row_it_owed(self, sessions, estate) -> None:
        message = await self._say(sessions, estate, "gone soon")
        await self._hold(WindowStore(sessions), estate, answer=True)
        async with sessions() as db:
            await db.execute(sql_delete(Message).where(Message.id == message))

        assert await self._rows(sessions) == []

    @pytest.mark.security
    async def test_the_answer_message_is_read_by_its_own_id_within_the_organization(
        self, sessions, estate
    ) -> None:
        org, _, run_id, _ = estate
        old = await self._say(sessions, estate, "old")
        await self._say(sessions, estate, "newer")
        async with sessions() as db:
            found = await conversation_repo.answer_message(
                db, old, run_id=run_id, organization_id=org.id
            )
            assert found is not None and found.content == "old"
            assert (
                await conversation_repo.answer_message(
                    db, old, run_id=run_id, organization_id=uuid.uuid4()
                )
                is None
            )
            assert (
                await conversation_repo.answer_message(
                    db, old, run_id=uuid.uuid4(), organization_id=org.id
                )
                is None
            )


NUDGE_NOW = datetime(2026, 11, 5, 8, tzinfo=UTC)
WRITTEN = NUDGE_NOW - timedelta(hours=21)
DESTINATION = {"bot_id": "b", "platform_chat_id": BSUID, "private_chat": True}


class TestNudges:
    """Who is nudged: a customer whose run waits on an approval in their own chat, once per window."""

    async def _waiting(
        self,
        db: AsyncSession,
        *,
        status: str = "awaiting_approval",
        paused_state: dict | str | None = "parked",
        active: bool = True,
        written: datetime | None = WRITTEN,
        closed: datetime | None = None,
        nudged: datetime | None = None,
        surface: str = "whatsapp",
    ) -> tuple[Organization, ChannelBot, WhatsAppCustomer, AgentRun]:
        if paused_state == "parked":
            paused_state = {"channel_destination": DESTINATION}
        org, bot, user, agent = await _estate(db)
        bot.is_active = active
        conversation = Conversation(user_id=user.id, organization_id=org.id)
        identity = ChannelIdentity(platform="whatsapp", platform_user_id=f"{org.id}:{BSUID}")
        db.add_all([conversation, identity])
        await db.flush()
        db.add(
            ChannelSession(
                bot_id=bot.id,
                identity_id=identity.id,
                conversation_id=conversation.id,
                platform_chat_id=BSUID,
            )
        )
        run = await _run(db, org, user, agent)
        run.conversation_id = conversation.id
        run.status = status
        run.surface = surface
        run.paused_state = paused_state
        customer = await _customer(db, org, bot)
        customer.last_inbound_at = written
        customer.window_closed_at = closed
        customer.nudged_at = nudged
        await db.flush()
        return org, bot, customer, run

    async def _candidates(self, db: AsyncSession) -> list[uuid.UUID]:
        found = await whatsapp_customer_repo.nudge_candidates(db, now=NUDGE_NOW)
        return [customer.id for customer in found]

    async def test_a_customer_whose_run_is_parked_in_their_chat_is_a_candidate(
        self, db: AsyncSession
    ) -> None:
        _, _, customer, _ = await self._waiting(db)
        assert await self._candidates(db) == [customer.id]

    async def test_a_customer_with_two_waiting_runs_is_listed_once(self, db: AsyncSession) -> None:
        org, bot, customer, run = await self._waiting(db)
        user = await db.get(User, run.user_id)
        agent = await db.get(Agent, run.agent_id)
        second = await _run(db, org, user, agent)
        second.conversation_id = run.conversation_id
        second.status = "awaiting_approval"
        second.surface = "whatsapp"
        second.paused_state = {"channel_destination": DESTINATION}
        await db.flush()
        assert await self._candidates(db) == [customer.id]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"status": "completed"},
            {"status": "awaiting_answer"},
            {"status": "running"},
            {"paused_state": None},
            {"paused_state": {}},
            {"paused_state": {"channel_destination": None}},
            {"surface": "web"},
            {"active": False},
            {"nudged": WRITTEN + timedelta(hours=20)},
            {"closed": WRITTEN + timedelta(seconds=1)},
            {"written": NUDGE_NOW - timedelta(hours=19, minutes=59)},
            {"written": NUDGE_NOW - timedelta(hours=23, minutes=55)},
            {"written": None},
        ],
        ids=lambda kwargs: "-".join(f"{key}={value}" for key, value in kwargs.items())[:60],
    )
    async def test_it_is_not_a_candidate_when(self, db: AsyncSession, kwargs) -> None:
        await self._waiting(db, **kwargs)
        assert await self._candidates(db) == []

    async def test_the_window_edges_are_the_rules_edges(self, db: AsyncSession) -> None:
        _, _, due, _ = await self._waiting(db, written=NUDGE_NOW - timedelta(hours=20))
        assert await self._candidates(db) == [due.id]

    async def test_a_closure_in_the_same_second_as_the_message_reads_reopened(
        self, db: AsyncSession
    ) -> None:
        _, _, customer, _ = await self._waiting(db, closed=WRITTEN)
        assert await self._candidates(db) == [customer.id]

    async def test_a_nudge_from_an_earlier_window_does_not_count(self, db: AsyncSession) -> None:
        _, _, customer, _ = await self._waiting(db, nudged=WRITTEN - timedelta(seconds=1))
        assert await self._candidates(db) == [customer.id]

    async def test_another_bots_customer_is_not_a_candidate(self, db: AsyncSession) -> None:
        org, bot, customer, run = await self._waiting(db, written=None)
        other = ChannelBot(
            organization_id=org.id,
            platform="whatsapp",
            name="Other",
            token_encrypted="x",
            whatsapp_phone_number_id="999",
            whatsapp_account_id="456",
        )
        db.add(other)
        await db.flush()
        stranger = await whatsapp_customer_repo.lock(
            db, organization_id=org.id, bot_id=other.id, bsuid=BSUID
        )
        stranger.last_inbound_at = WRITTEN
        await db.flush()
        assert await self._candidates(db) == []

    async def test_only_the_customer_with_the_waiting_run_in_their_own_chat_is_listed(
        self, db: AsyncSession
    ) -> None:
        org, bot, waiting, run = await self._waiting(db)
        user = await db.get(User, run.user_id)
        agent = await db.get(Agent, run.agent_id)
        # Another customer of the same bot, in a chat of their own with nothing waiting.
        bystander = await whatsapp_customer_repo.lock(
            db, organization_id=org.id, bot_id=bot.id, bsuid="US.222"
        )
        bystander.last_inbound_at = WRITTEN
        chat = Conversation(user_id=user.id, organization_id=org.id)
        identity = ChannelIdentity(platform="whatsapp", platform_user_id=f"{org.id}:US.222")
        db.add_all([chat, identity])
        await db.flush()
        db.add(
            ChannelSession(
                bot_id=bot.id,
                identity_id=identity.id,
                conversation_id=chat.id,
                platform_chat_id="US.222",
            )
        )
        # A run waiting in an older conversation that no session points at any more.
        older = Conversation(user_id=user.id, organization_id=org.id)
        db.add(older)
        await db.flush()
        parked = await _run(db, org, user, agent)
        parked.conversation_id = older.id
        parked.status = "awaiting_approval"
        parked.surface = "whatsapp"
        parked.paused_state = {"channel_destination": DESTINATION}
        await db.flush()

        assert await self._candidates(db) == [waiting.id]

    @pytest.mark.security
    async def test_another_organizations_customer_is_not_a_candidate(
        self, db: AsyncSession
    ) -> None:
        _, bot, customer, run = await self._waiting(db)
        stranger_org = Organization(
            name="Other", slug=f"o-{uuid.uuid4().hex[:8]}", created_by_user_id=run.user_id
        )
        db.add(stranger_org)
        await db.flush()
        run.organization_id = stranger_org.id
        await db.flush()
        assert await self._candidates(db) == []

    async def test_the_oldest_message_comes_first_and_the_limit_holds(
        self, db: AsyncSession
    ) -> None:
        _, _, newer, _ = await self._waiting(db, written=NUDGE_NOW - timedelta(hours=21))
        _, _, older, _ = await self._waiting(db, written=NUDGE_NOW - timedelta(hours=22))
        assert await self._candidates(db) == [older.id, newer.id]
        limited = await whatsapp_customer_repo.nudge_candidates(db, now=NUDGE_NOW, limit=1)
        assert [customer.id for customer in limited] == [older.id]


class TestMarkingANudge:
    async def _customer_id(self, sessions, *, written=WRITTEN, nudged=None) -> uuid.UUID:
        async with sessions() as db:
            org, bot, _, _ = await _estate(db)
            customer = await _customer(db, org, bot)
            customer.last_inbound_at = written
            customer.nudged_at = nudged
            return customer.id

    async def _mark(self, sessions, customer_id: uuid.UUID, *, now=NUDGE_NOW) -> bool:
        async with sessions() as db:
            return await whatsapp_customer_repo.mark_nudged(db, customer_id=customer_id, now=now)

    async def test_a_due_customer_is_marked_with_the_time(self, sessions) -> None:
        customer_id = await self._customer_id(sessions)
        assert await self._mark(sessions, customer_id)
        async with sessions() as db:
            assert (await db.get(WhatsAppCustomer, customer_id)).nudged_at == NUDGE_NOW

    async def test_two_sweeps_racing_for_one_customer_mark_it_once(self, sessions) -> None:
        customer_id = await self._customer_id(sessions)
        results = await asyncio.gather(
            self._mark(sessions, customer_id), self._mark(sessions, customer_id)
        )
        assert sorted(results) == [False, True]

    async def test_a_customer_nudged_while_the_sweep_waited_is_not_marked_again(
        self, sessions
    ) -> None:
        customer_id = await self._customer_id(sessions)
        async with sessions() as holder:
            await holder.execute(
                select(WhatsAppCustomer).where(WhatsAppCustomer.id == customer_id).with_for_update()
            )
            second = asyncio.create_task(self._mark(sessions, customer_id))
            await asyncio.sleep(0.2)
            assert not second.done()
            (await holder.get(WhatsAppCustomer, customer_id)).nudged_at = NUDGE_NOW
        assert await second is False

    async def test_a_customer_who_wrote_again_is_not_marked_for_the_old_window(
        self, sessions
    ) -> None:
        customer_id = await self._customer_id(sessions, written=NUDGE_NOW - timedelta(hours=1))
        assert not await self._mark(sessions, customer_id)

    async def test_an_unknown_customer_is_not_marked(self, sessions) -> None:
        assert not await self._mark(sessions, uuid.uuid4())
