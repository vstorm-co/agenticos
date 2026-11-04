"""Channel prompts against Postgres: what a press can find, and in what order (#2064)."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import RunStatus
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_prompt import APPROVAL, FOLLOW_UP, QUESTION, ChannelPrompt
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent_run_repo, channel_prompt_repo

pytestmark = pytest.mark.anyio


async def _estate(db: AsyncSession) -> tuple[Organization, ChannelBot, uuid.UUID]:
    user = User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    bot = ChannelBot(organization_id=org.id, platform="slack", name="Support", token_encrypted="x")
    agent = Agent(organization_id=org.id, slug=f"a-{uuid.uuid4().hex[:6]}", name="A", draft_spec={})
    db.add_all([bot, agent])
    await db.flush()
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=user.id,
        conversation_id=None,
        surface="slack",
        model_label="m",
        provider="openai",
        secret_id=None,
        started_at=datetime.now(UTC),
    )
    return org, bot, run.id


async def test_a_typed_answer_finds_the_oldest_open_question_put_to_its_sender(
    db: AsyncSession,
) -> None:
    org, bot, run_id = await _estate(db)
    run = await agent_run_repo.get_run(db, run_id, organization_id=org.id)
    assert run is not None and run.user_id is not None
    run.status = RunStatus.AWAITING_ANSWER.value

    async def ask(index: int, *, allow_custom: bool, chat: str = "C1") -> uuid.UUID:
        prompt = await channel_prompt_repo.create(
            db,
            organization_id=org.id,
            bot_id=bot.id,
            run_id=run_id,
            platform_chat_id=chat,
            kind=QUESTION,
            tool_call_id="ask-1",
            question_index=index,
            choices=[],
            allow_custom=allow_custom,
        )
        return prompt.id

    await ask(0, allow_custom=False)
    typed = await ask(1, allow_custom=True)
    await ask(2, allow_custom=True, chat="C2")

    def find(user_id: uuid.UUID, chat: str = "C1"):
        return channel_prompt_repo.claim_typed(
            db, bot_id=bot.id, platform_chat_id=chat, user_id=user_id
        )

    found = await find(run.user_id)
    assert found is not None and found.id == typed
    # Somebody else in the chat is not the person asked.
    assert await find(uuid.uuid4()) is None

    await channel_prompt_repo.answer(db, prompt=found, value={"answer": "Kraków"})
    assert await find(run.user_id) is None

    # And a run no longer waiting has nothing to answer.
    run.status = RunStatus.COMPLETED.value
    await db.flush()
    assert await find(run.user_id, "C2") is None


async def test_a_question_s_rows_come_back_in_order_and_record_their_answers(
    db: AsyncSession,
) -> None:
    org, bot, run_id = await _estate(db)
    for index in (1, 0):
        await channel_prompt_repo.create(
            db,
            organization_id=org.id,
            bot_id=bot.id,
            run_id=run_id,
            platform_chat_id="C1",
            kind=QUESTION,
            tool_call_id="ask-1",
            question_index=index,
            choices=["A", "B"],
        )

    rows = await channel_prompt_repo.for_call(db, run_id=run_id, tool_call_id="ask-1")
    answered = await channel_prompt_repo.answer(db, prompt=rows[0], value={"selected": ["A"]})

    assert [row.question_index for row in rows] == [0, 1]
    assert answered.answer == {"selected": ["A"]} and answered.answered_at is not None
    assert "ChannelPrompt" in repr(answered)


@pytest.mark.security
async def test_a_press_through_another_bot_finds_nothing(db: AsyncSession) -> None:
    org, bot, run_id = await _estate(db)
    prompt = await channel_prompt_repo.create(
        db,
        organization_id=org.id,
        bot_id=bot.id,
        run_id=run_id,
        platform_chat_id="C1",
        kind=QUESTION,
        tool_call_id="ask-1",
        question_index=0,
        choices=["A"],
    )
    _other_org, other_bot, _ = await _estate(db)

    assert await channel_prompt_repo.claim(db, prompt.id, bot_id=bot.id) is not None
    assert await channel_prompt_repo.claim(db, prompt.id, bot_id=other_bot.id) is None


async def test_an_approval_prompt_must_name_its_approval(db: AsyncSession) -> None:
    org, bot, run_id = await _estate(db)

    with pytest.raises(IntegrityError):
        await channel_prompt_repo.create(
            db,
            organization_id=org.id,
            bot_id=bot.id,
            run_id=run_id,
            platform_chat_id="C1",
            kind=APPROVAL,
            choices=["Approve", "Reject"],
        )


async def test_next_steps_keep_the_kind_of_chat_a_press_is_replayed_into(
    db: AsyncSession,
) -> None:
    """A press does not say whether its chat is private or a group, so the row
    must (#2301)."""
    org, bot, run_id = await _estate(db)

    kept = await channel_prompt_repo.create(
        db,
        organization_id=org.id,
        bot_id=bot.id,
        run_id=run_id,
        platform_chat_id="C1",
        kind=FOLLOW_UP,
        choices=["Make it a table"],
        chat_type="group",
    )
    assert kept.chat_type == "group"

    with pytest.raises(IntegrityError):
        await channel_prompt_repo.create(
            db,
            organization_id=org.id,
            bot_id=bot.id,
            run_id=run_id,
            platform_chat_id="C1",
            kind=FOLLOW_UP,
            choices=["Make it a table"],
        )


async def _approval_prompt(
    db: AsyncSession, org: Organization, bot: ChannelBot, run_id: uuid.UUID, *, tool: str = "t"
):
    from app.db.models.agent_run import ApprovalStatus, ToolApproval

    run = await agent_run_repo.get_run(db, run_id, organization_id=org.id)
    assert run is not None
    approval = ToolApproval(
        organization_id=org.id,
        run_id=run_id,
        agent_id=run.agent_id,
        tool_id=tool,
        tool_args={},
        status=ApprovalStatus.PENDING.value,
    )
    db.add(approval)
    await db.flush()
    prompt = await channel_prompt_repo.create(
        db,
        organization_id=org.id,
        bot_id=bot.id,
        run_id=run_id,
        platform_chat_id="C1",
        kind=APPROVAL,
        approval_id=approval.id,
        choices=["Approve", "Reject"],
    )
    return approval, prompt


async def _question_prompt(
    db: AsyncSession,
    org: Organization,
    bot: ChannelBot,
    run_id: uuid.UUID,
    *,
    call: str = "q",
    index: int = 0,
):
    return await channel_prompt_repo.create(
        db,
        organization_id=org.id,
        bot_id=bot.id,
        run_id=run_id,
        platform_chat_id="C1",
        kind=QUESTION,
        tool_call_id=call,
        question_index=index,
        choices=["A"],
        allow_custom=True,
    )


@pytest.mark.security
async def test_settling_marks_every_open_approval_and_question_of_the_run_and_nothing_else(
    db: AsyncSession,
) -> None:
    org, bot, run_a = await _estate(db)
    _, _, run_b = await _estate(db)
    _, open_approval = await _approval_prompt(db, org, bot, run_a)
    open_question = await _question_prompt(db, org, bot, run_a)
    _, answered = await _approval_prompt(db, org, bot, run_a)
    await channel_prompt_repo.answer(db, prompt=answered, value={"decision": "approved"})
    follow_up = await channel_prompt_repo.create(
        db,
        organization_id=org.id,
        bot_id=bot.id,
        run_id=run_a,
        platform_chat_id="C1",
        kind=FOLLOW_UP,
        choices=["More"],
        chat_type="group",
    )
    other = await _question_prompt(db, org, bot, run_b)

    settled = await channel_prompt_repo.settle_open(db, run_id=run_a, by="stopped")

    assert settled == 2
    for row in (open_approval, open_question):
        await db.refresh(row)
        assert row.answered_at is not None and row.answer == {"settled": "stopped"}
    await db.refresh(answered)
    assert answered.answer == {"decision": "approved"}
    await db.refresh(follow_up)
    await db.refresh(other)
    assert follow_up.answered_at is None and other.answered_at is None


@pytest.mark.security
async def test_settling_one_approval_leaves_the_runs_other_approval_pressable(
    db: AsyncSession,
) -> None:
    org, bot, run_id = await _estate(db)
    first, _ = await _approval_prompt(db, org, bot, run_id)
    _, second_prompt = await _approval_prompt(db, org, bot, run_id)

    settled = await channel_prompt_repo.settle_open(
        db, run_id=run_id, by="decided", approval_id=first.id
    )

    assert settled == 1
    await db.refresh(second_prompt)
    assert second_prompt.answered_at is None


async def test_a_row_a_press_holds_is_skipped_not_waited_for(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    org, bot, run_id = await _estate(db)
    _, held = await _approval_prompt(db, org, bot, run_id)
    free = await _question_prompt(db, org, bot, run_id)
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as presser, factory() as settler:
        assert await channel_prompt_repo.claim(presser, held.id, bot_id=bot.id) is not None

        settled = await asyncio.wait_for(
            channel_prompt_repo.settle_open(settler, run_id=run_id, by="decided"), 2
        )
        await settler.commit()
        await presser.rollback()

    assert settled == 1
    async with factory() as check:
        rows = {
            row.id: row.answered_at
            for row in (
                await check.execute(
                    select(ChannelPrompt).where(ChannelPrompt.id.in_([held.id, free.id]))
                )
            ).scalars()
        }
    assert rows[held.id] is None and rows[free.id] is not None


async def test_a_typed_answer_after_settling_finds_the_new_question(db: AsyncSession) -> None:
    org, bot, run_id = await _estate(db)
    run = await agent_run_repo.get_run(db, run_id, organization_id=org.id)
    assert run is not None and run.user_id is not None
    run.status = RunStatus.AWAITING_ANSWER.value
    await _question_prompt(db, org, bot, run_id, call="old")

    await channel_prompt_repo.settle_open(db, run_id=run_id, by="answered")
    # Same transaction, same `created_at`: the index is what puts the new row
    # after the old one, so only a real settle lets `claim_typed` skip the old.
    fresh = await _question_prompt(db, org, bot, run_id, call="new", index=1)

    found = await channel_prompt_repo.claim_typed(
        db, bot_id=bot.id, platform_chat_id="C1", user_id=run.user_id
    )
    assert found is not None and found.id == fresh.id


async def test_settling_a_run_with_nothing_open_settles_nothing(db: AsyncSession) -> None:
    _, _, run_id = await _estate(db)

    assert await channel_prompt_repo.settle_open(db, run_id=run_id, by="expired") == 0
