"""History checkpoints advance monotonically and remain fenced by refusals."""

import asyncio
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.ephemeral_media import dump_messages
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import conversation_repo
from app.schemas.conversation import HistoryCheckpointFrontier
from app.services.conversation import ConversationService
from tests.history_fixtures import CHECKPOINT_PROVENANCE as _PROVENANCE
from tests.history_fixtures import stored_checkpoint as _checkpoint

pytestmark = pytest.mark.anyio


async def test_an_older_answer_cannot_replace_a_newer_checkpoint(db: AsyncSession) -> None:
    person = User(
        id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
    )
    db.add(person)
    await db.flush()
    organization = Organization(
        id=uuid4(), name="History", slug=uuid4().hex, created_by_user_id=person.id
    )
    db.add(organization)
    await db.flush()
    conversation = Conversation(id=uuid4(), user_id=person.id, organization_id=organization.id)
    db.add(conversation)
    await db.flush()
    first = await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="assistant", content="First"
    )
    second = await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="assistant", content="Second"
    )
    service = ConversationService(db)
    newer = dump_messages([ModelRequest(parts=[UserPromptPart("Newer evidence")])])
    older = dump_messages([ModelRequest(parts=[UserPromptPart("Older evidence")])])
    await service.keep_summary(
        conversation.id,
        newer,
        expected_revision=0,
        expected_frontier=HistoryCheckpointFrontier(
            summary_ordinal=None, message_ordinal=second.ordinal
        ),
        through_message_id=str(second.id),
        provenance=_PROVENANCE,
    )
    await service.keep_summary(
        conversation.id,
        older,
        expected_revision=0,
        expected_frontier=HistoryCheckpointFrontier(
            summary_ordinal=None, message_ordinal=first.ordinal
        ),
        through_message_id=str(first.id),
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)
    assert conversation.summary_ordinal == second.ordinal
    assert conversation.summary_messages == _checkpoint(newer)


async def _thread(db: AsyncSession) -> tuple[Conversation, Agent]:
    person = User(email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(person)
    await db.flush()
    organization = Organization(name="History", slug=uuid4().hex, created_by_user_id=person.id)
    db.add(organization)
    await db.flush()
    conversation = Conversation(user_id=person.id, organization_id=organization.id)
    agent = Agent(
        organization_id=organization.id,
        name="Reader",
        slug=uuid4().hex,
        draft_spec={"name": "Reader"},
    )
    db.add_all([conversation, agent])
    await db.flush()
    await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="user", content="Initial"
    )
    return conversation, agent


async def _run(db: AsyncSession, conversation: Conversation, agent: Agent) -> AgentRun:
    run = AgentRun(
        organization_id=conversation.organization_id,
        agent_id=agent.id,
        user_id=conversation.user_id,
        surface="api",
        status="completed",
    )
    db.add(run)
    await db.flush()
    return run


async def test_a_prompt_written_after_reading_history_belongs_to_its_own_checkpoint(
    db: AsyncSession,
) -> None:
    conversation, agent = await _thread(db)
    run = await _run(db, conversation, agent)
    service = ConversationService(db)
    history = await service.model_history(conversation.id, limit=50)
    await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="user", content="Own prompt", run_id=run.id
    )
    answer = await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="assistant", content="Own answer", run_id=run.id
    )
    snapshot = dump_messages(
        [ModelRequest(parts=[UserPromptPart("Initial; own prompt; own answer and tool evidence")])]
    )
    answer_id, answer_ordinal = answer.id, answer.ordinal
    db.expunge(answer)
    await service.keep_summary(
        conversation.id,
        snapshot,
        expected_revision=history.revision,
        expected_frontier=history.frontier,
        through_message_id=str(answer_id),
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)
    assert conversation.summary_ordinal == answer_ordinal
    assert conversation.summary_messages == _checkpoint(snapshot)


@pytest.mark.parametrize("late_role", ["user", "assistant"])
async def test_a_checkpoint_never_skips_an_intervening_turn_before_its_answer(
    db: AsyncSession,
    late_role: str,
) -> None:
    conversation, agent = await _thread(db)
    run = await _run(db, conversation, agent)
    service = ConversationService(db)
    history = await service.model_history(conversation.id, limit=50)
    await conversation_repo.create_message(
        db, conversation_id=conversation.id, role=late_role, content="INTERVENING_VISIBLE_EVIDENCE"
    )
    answer = await conversation_repo.create_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content="OWN_VISIBLE_ANSWER",
        run_id=run.id,
    )
    await service.keep_summary(
        conversation.id,
        dump_messages(
            [ModelRequest(parts=[UserPromptPart("A snapshot that never saw the intervening turn")])]
        ),
        expected_revision=history.revision,
        expected_frontier=history.frontier,
        through_message_id=str(answer.id),
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)
    assert conversation.summary_messages is None and conversation.summary_ordinal is None
    replayed = str(dump_messages(await service.model_history(conversation.id, limit=50)))
    assert "INTERVENING_VISIBLE_EVIDENCE" in replayed and "OWN_VISIBLE_ANSWER" in replayed


async def test_concurrent_turns_cannot_replace_the_checkpoint_they_did_not_read(
    db: AsyncSession,
    engine: AsyncEngine,
) -> None:
    conversation, agent = await _thread(db)
    first_run, second_run = await _run(db, conversation, agent), await _run(db, conversation, agent)
    conversation_id, first_run_id, second_run_id = conversation.id, first_run.id, second_run.id
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    both_read = asyncio.Barrier(2)
    first_committed = asyncio.Event()

    async def complete(name: str, run_id: UUID) -> None:
        async with factory() as session:
            service = ConversationService(session)
            history = await service.model_history(conversation_id, limit=50)
            await session.commit()
            await both_read.wait()
            if name == "SECOND":
                await first_committed.wait()
            answer = await conversation_repo.create_message(
                session,
                conversation_id=conversation_id,
                role="assistant",
                content=f"{name}_VISIBLE_ANSWER",
                run_id=run_id,
            )
            await service.keep_summary(
                conversation_id,
                dump_messages([ModelRequest(parts=[UserPromptPart(f"{name}_MODEL_EVIDENCE")])]),
                expected_revision=history.revision,
                expected_frontier=history.frontier,
                through_message_id=str(answer.id),
                provenance=_PROVENANCE,
            )
            await session.commit()
            if name == "FIRST":
                first_committed.set()

    async with asyncio.timeout(10):
        await asyncio.gather(complete("FIRST", first_run_id), complete("SECOND", second_run_id))
    async with factory() as session:
        stored = await conversation_repo.get_conversation_by_id(
            session, conversation_id, include_summary=True
        )
        assert stored is not None and "FIRST_MODEL_EVIDENCE" in str(stored.summary_messages)
        assert "SECOND_MODEL_EVIDENCE" not in str(stored.summary_messages)
        replayed = str(
            dump_messages(
                await ConversationService(session).model_history(conversation_id, limit=50)
            )
        )
        assert "FIRST_MODEL_EVIDENCE" in replayed and "SECOND_VISIBLE_ANSWER" in replayed


@pytest.mark.parametrize("writer", ["message", "workflow", "voice"])
async def test_a_blocked_message_writer_cannot_allocate_an_ordinal_below_a_checkpoint(
    db: AsyncSession,
    engine: AsyncEngine,
    writer: str,
) -> None:
    conversation, agent = await _thread(db)
    run = await _run(db, conversation, agent)
    conversation_id, run_id, agent_id = conversation.id, run.id, agent.id
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    writer_started: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    sequence_value = text(
        "SELECT pg_sequence_last_value(pg_get_serial_sequence('messages', 'ordinal')::regclass)"
    )

    async def write() -> None:
        async with factory() as session:
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            writer_started.set_result(pid)
            if writer == "message":
                await conversation_repo.create_message(
                    session,
                    conversation_id=conversation_id,
                    role="assistant",
                    content="Later writer",
                )
            elif writer == "workflow":
                await conversation_repo.save_workflow_message(
                    session,
                    conversation_id=conversation_id,
                    workflow_run_id=uuid4(),
                    content="Later workflow answer",
                    parts=[],
                )
            else:
                await conversation_repo.create_voice_turn(
                    session,
                    conversation_id=conversation_id,
                    role="assistant",
                    content="Later voice answer",
                    turn_id="turn:answer",
                    interrupted=False,
                    run_id=run_id,
                    agent_id=agent_id,
                    agent_version_id=None,
                    parts=[],
                )
            await session.commit()

    async with factory() as blocker, factory() as observer:
        await blocker.execute(
            select(Conversation.id).where(Conversation.id == conversation_id).with_for_update()
        )
        before = await observer.scalar(sequence_value)
        task = asyncio.create_task(write())
        try:
            async with asyncio.timeout(10):
                pid = await writer_started
                for _ in range(1000):
                    if await observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                    ):
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail("The writer did not reach the held conversation lock")
            assert await observer.scalar(sequence_value) == before
        finally:
            await blocker.rollback()
            await task


async def test_internal_compaction_can_replace_exactly_the_frontier_it_read(
    db: AsyncSession,
) -> None:
    conversation, _ = await _thread(db)
    service = ConversationService(db)
    history = await service.model_history(conversation.id, limit=50)
    await service.keep_summary(
        conversation.id,
        dump_messages(history),
        expected_revision=history.revision,
        expected_frontier=history.frontier,
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)
    assert conversation.summary_messages == _checkpoint(dump_messages(history))
    assert (
        history.frontier is not None
        and conversation.summary_ordinal == history.frontier.message_ordinal
    )


async def test_a_frontier_match_cannot_cross_a_new_refusal_revision(db: AsyncSession) -> None:
    from sqlalchemy import update

    conversation, agent = await _thread(db)
    run = await _run(db, conversation, agent)
    service = ConversationService(db)
    history = await service.model_history(conversation.id, limit=50)
    await db.execute(
        update(Conversation).where(Conversation.id == conversation.id).values(guardrail_revision=1)
    )
    answer = await conversation_repo.create_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content="Old-run answer",
        run_id=run.id,
    )
    await service.keep_summary(
        conversation.id,
        dump_messages(history),
        expected_revision=history.revision,
        expected_frontier=history.frontier,
        through_message_id=str(answer.id),
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)
    assert conversation.summary_messages is None and conversation.summary_ordinal is None


async def test_a_workflow_placeholder_finishing_after_history_was_read_stays_replayable(
    db: AsyncSession,
) -> None:
    conversation, agent = await _thread(db)
    run = await _run(db, conversation, agent)
    workflow_id = uuid4()
    pending = await conversation_repo.save_workflow_message(
        db,
        conversation_id=conversation.id,
        workflow_run_id=workflow_id,
        content="Workflow pending",
        parts=[],
    )
    pending_ordinal = pending.ordinal
    service = ConversationService(db)
    history = await service.model_history(conversation.id, limit=50)
    finished = await conversation_repo.save_workflow_message(
        db,
        conversation_id=conversation.id,
        workflow_run_id=workflow_id,
        content="WORKFLOW_FINISHED_EVIDENCE",
        parts=[],
    )
    assert finished.ordinal > pending_ordinal
    answer = await conversation_repo.create_message(
        db, conversation_id=conversation.id, role="assistant", content="Own answer", run_id=run.id
    )
    await service.keep_summary(
        conversation.id,
        dump_messages(history),
        expected_revision=history.revision,
        expected_frontier=history.frontier,
        through_message_id=str(answer.id),
        provenance=_PROVENANCE,
    )
    await db.refresh(conversation)
    assert conversation.summary_messages is None
    assert "WORKFLOW_FINISHED_EVIDENCE" in str(
        dump_messages(await service.model_history(conversation.id, limit=50))
    )
