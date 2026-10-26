"""Late buttons append atomically to the intended answer under PostgreSQL."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_repo

pytestmark = pytest.mark.anyio


async def fixture_rows(db):
    user = User(id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Acme", slug=f"acme-{uuid4().hex}", created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    agent = Agent(
        id=uuid4(),
        name="Helper",
        slug=f"helper-{uuid4().hex}",
        organization_id=org.id,
        created_by_user_id=user.id,
    )
    conversation = Conversation(id=uuid4(), user_id=user.id, organization_id=org.id)
    db.add_all([agent, conversation])
    await db.flush()
    run = AgentRun(
        id=uuid4(),
        agent_id=agent.id,
        organization_id=org.id,
        conversation_id=conversation.id,
        user_id=user.id,
        status="completed",
        started_at=datetime.now(UTC),
    )
    other = AgentRun(
        id=uuid4(),
        agent_id=agent.id,
        organization_id=org.id,
        conversation_id=conversation.id,
        user_id=user.id,
        status="completed",
        started_at=datetime.now(UTC),
    )
    db.add_all([run, other])
    await db.flush()

    async def message(role, text, run_id, parts=None):
        return await conversation_repo.create_message(
            db, conversation_id=conversation.id, role=role, content=text, run_id=run_id, parts=parts
        )

    prompt = await message("user", "This question", run.id)
    await message("user", "Someone else's question", other.id)
    answer = await message(
        "assistant", "This answer", run.id, [{"type": "text", "text": "This answer"}]
    )
    next_answer = await message("assistant", "A later answer", other.id)
    return org, conversation, run, prompt, answer, next_answer


async def test_buttons_are_persisted_on_the_exact_answer_once_and_replayed(db):
    org, conversation, run, prompt, answer, next_answer = await fixture_rows(db)
    assert await conversation_repo.prompt_for_answer(db, answer) == prompt.content
    assert await conversation_repo.last_answer_message(db, run.id, organization_id=org.id) is answer
    assert await conversation_repo.store_next_steps(
        db, message_id=answer.id, organization_id=org.id, steps=["Zrób tabelę"]
    )
    assert not await conversation_repo.store_next_steps(
        db, message_id=answer.id, organization_id=org.id, steps=["Duplicate"]
    )
    rows = await conversation_repo.get_messages_by_run(db, run.id, include_tool_calls=True)
    saved = next(row for row in rows if row.id == answer.id)
    assert len(saved.tool_calls) == 1
    assert json.loads(saved.tool_calls[0].result) == {"steps": ["Zrób tabelę"]}
    assert saved.parts[-1] == {"type": "tool", "tool_call_id": f"next_steps_{answer.id}"}
    assert next_answer.content == "A later answer"
    assert next_answer.parts is None


async def test_missing_archived_and_other_tenant_answers_are_not_mutated(db):
    org, conversation, run, prompt, answer, _ = await fixture_rows(db)
    assert await conversation_repo.last_answer_message(db, run.id, organization_id=uuid4()) is None
    assert not await conversation_repo.store_next_steps(
        db, message_id=answer.id, organization_id=uuid4(), steps=["No"]
    )
    assert not await conversation_repo.store_next_steps(
        db, message_id=uuid4(), organization_id=org.id, steps=["No"]
    )
    conversation.is_archived = True
    await db.flush()
    assert not await conversation_repo.store_next_steps(
        db, message_id=answer.id, organization_id=org.id, steps=["No"]
    )
    assert await conversation_repo.prompt_for_answer(db, prompt) == ""


async def test_a_flat_transcript_remains_flat(db):
    org, _, _, _, _, answer = await fixture_rows(db)
    assert await conversation_repo.store_next_steps(
        db, message_id=answer.id, organization_id=org.id, steps=["Next"]
    )
    assert answer.parts is None


async def test_auxiliary_run_keeps_conversation_acl_and_cost_without_marking_it_busy(db):
    from decimal import Decimal

    from app.repositories import agent_run_repo

    org, conversation, parent, _, answer, _ = await fixture_rows(db)
    auxiliary = AgentRun(
        id=uuid4(),
        organization_id=org.id,
        agent_id=parent.agent_id,
        user_id=parent.user_id,
        surface="follow_ups",
        status="running",
        started_at=datetime.now(UTC),
    )
    db.add(auxiliary)
    await db.flush()
    await agent_run_repo.associate_auxiliary_conversation(db, auxiliary, conversation.id)
    assert auxiliary.conversation_id == parent.conversation_id
    assert await conversation_repo.running_since(db, [conversation.id]) == {}
    assert await conversation_repo.running_users(db, [conversation.id]) == {}
    assert (
        await agent_run_repo.latest_run_for_conversation(
            db, conversation.id, organization_id=org.id
        )
    ).id != auxiliary.id
    answer.input_tokens = 10
    answer.output_tokens = 20
    answer.cost_usd = Decimal("0.5")
    answer.cost_is_partial = False
    auxiliary.input_tokens = 1
    auxiliary.output_tokens = 2
    auxiliary.cost_usd = Decimal("0.01")
    auxiliary.cost_is_partial = False
    auxiliary.ended_at = datetime.now(UTC)
    auxiliary.status = "completed"
    await db.flush()
    assert await conversation_repo.conversation_cost(db, conversation.id) == (
        11,
        22,
        Decimal("0.51"),
        False,
    )


async def test_locked_append_refreshes_a_previously_loaded_answer(db, engine):
    from sqlalchemy.ext.asyncio import AsyncSession

    org, _, _, _, answer, _ = await fixture_rows(db)
    await db.commit()
    async with AsyncSession(engine, expire_on_commit=False) as other:
        changed = await other.get(Message, answer.id)
        changed.parts = [*changed.parts, {"type": "text", "text": "Written after the first read"}]
        await other.commit()
    assert len(answer.parts) == 1
    assert await conversation_repo.store_next_steps(
        db, message_id=answer.id, organization_id=org.id, steps=["Next"]
    )
    assert answer.parts[1] == {"type": "text", "text": "Written after the first read"}
    assert answer.parts[2]["tool_call_id"] == f"next_steps_{answer.id}"
