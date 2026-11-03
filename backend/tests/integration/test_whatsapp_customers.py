"""The WhatsApp customer record and the store over it, against Postgres (#2076)."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.channel_bot import ChannelBot
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.models.whatsapp_customer import WhatsAppCustomer, WhatsAppHeldRun
from app.repositories import agent_run_repo, whatsapp_customer_repo
from app.services.channels.whatsapp_customers import Held, WindowStore
from app.services.channels.whatsapp_templates import LateTemplate, to_stored
from app.services.channels.whatsapp_window import CLAIM_LEASE

pytestmark = pytest.mark.anyio

T1 = datetime(2026, 11, 4, 10, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)
T3 = T1 + timedelta(hours=2)
BSUID = "US.111"


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
    assert not await whatsapp_customer_repo.has_held(db, bot_id=bot.id, bsuid=BSUID)
    await whatsapp_customer_repo.hold_run(
        db, customer=customer, run_id=run.id, answer=True, files=False
    )
    assert await whatsapp_customer_repo.has_held(db, bot_id=bot.id, bsuid=BSUID)
    [row] = await whatsapp_customer_repo.held_runs(db, customer=customer, claimable_before=T3)
    await whatsapp_customer_repo.update_held(db, held=row, update_data={"claimed_at": T1})
    assert await whatsapp_customer_repo.held_runs(db, customer=customer, claimable_before=T1) == []
    await whatsapp_customer_repo.delete_held(db, held_id=row.id)
    assert not await whatsapp_customer_repo.has_held(db, bot_id=bot.id, bsuid=BSUID)


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
    def sessions(
        self, engine: AsyncEngine
    ) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
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
        assert not await store.has_held(str(bot.id), BSUID)
        late = T1 + timedelta(hours=30)
        assert not await store.hold_unless_open(
            str(bot.id), BSUID, run_id=str(runs[0]), answer=True, files=False, now=late
        )
        assert await store.has_held(str(bot.id), BSUID)

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
        assert len(await store.claim_held(str(bot.id), BSUID, now=T3)) == 1
        await store.answer_sent(held, prompts_owed=False)
        assert await self._reason(sessions, runs[0]) is None
        assert not await store.has_held(str(bot.id), BSUID)

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
        assert await store.has_held(str(bot.id), BSUID)
        assert await store.claim_held(str(bot.id), BSUID, now=T3) == []
        async with sessions() as db:
            row = (await db.execute(select(WhatsAppHeldRun))).scalar_one()
            assert (row.held_answer, row.held_files, row.claimed_at) == (False, False, T3)
        await store.done(held)
        assert not await store.has_held(str(bot.id), BSUID)

    async def test_hold_new_is_true_once_per_run(self, sessions, estate) -> None:
        _, bot, runs = estate
        store = WindowStore(sessions)
        assert await store.hold_new(str(bot.id), BSUID, run_id=str(runs[0]))
        assert not await store.hold_new(str(bot.id), BSUID, run_id=str(runs[0]))
        assert await store.hold_new(str(bot.id), BSUID, run_id=str(runs[1]))

    async def test_a_closure_is_news_once_per_message(self, sessions, estate) -> None:
        org, bot, _ = estate
        store = WindowStore(sessions)
        await self._record(sessions, org, bot, T1)
        assert await store.close(str(bot.id), BSUID, at=T1 + timedelta(minutes=1))
        assert not await store.close(str(bot.id), BSUID, at=T1 + timedelta(minutes=2))
        assert await store.window(str(bot.id), BSUID, now=T1 + timedelta(minutes=3)) is False
        await self._record(sessions, org, bot, T2)
        assert not await store.close(str(bot.id), BSUID, at=T1 + timedelta(minutes=30))
        assert await store.window(str(bot.id), BSUID, now=T2 + timedelta(minutes=1)) is True

    async def test_no_record_reads_as_none(self, sessions, estate) -> None:
        _, bot, _ = estate
        store = WindowStore(sessions)
        assert await store.window(str(bot.id), BSUID, now=T3) is None
        assert not await store.has_held(str(bot.id), BSUID)

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

    async def _reason(
        self, sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]], run_id: uuid.UUID
    ) -> str | None:
        async with sessions() as db:
            row = await db.get(AgentRun, run_id)
            assert row is not None
            await db.refresh(row)
            return row.undelivered_reason
