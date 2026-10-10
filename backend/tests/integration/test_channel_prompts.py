"""Channel prompts against Postgres: what a press can find, and in what order (#2064)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_prompt import APPROVAL, QUESTION
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
