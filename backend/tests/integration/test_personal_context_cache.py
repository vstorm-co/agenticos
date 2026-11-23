"""Real source revision fences and membership-scoped checkpoint persistence."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Message
from app.repositories import personal_context as cache
from tests.integration.test_system_agents import _chat_run, _transcript, _world

pytestmark = pytest.mark.anyio


async def test_revisions_notice_edits_refusals_and_native_answer_changes(db: AsyncSession) -> None:
    user, org, agent, version, *_ = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(
        db, conversation, run, [("user", "A real request"), ("assistant", "A response")]
    )
    first = await cache.conversation_revision(
        db, organization_id=org.id, conversation_id=conversation.id
    )
    assert len(first) == 64
    assert (
        await cache.conversation_revision(
            db, organization_id=uuid4(), conversation_id=conversation.id
        )
        == "missing"
    )
    message = await db.scalar(
        select(Message).where(Message.conversation_id == conversation.id, Message.role == "user")
    )
    assert message is not None
    await db.execute(
        text("UPDATE messages SET content = 'Edited request' WHERE id = :id"), {"id": message.id}
    )
    second = await cache.conversation_revision(
        db, organization_id=org.id, conversation_id=conversation.id
    )
    assert second != first
    message.guardrail_refused = True
    await db.flush()
    assert (
        await cache.conversation_revision(
            db, organization_id=org.id, conversation_id=conversation.id
        )
        != second
    )
    page = await cache.transcript_page(
        db, organization_id=org.id, conversation_id=conversation.id, after=-1, since=run.started_at
    )
    assert all(row.role != "user" for row, _ in page)


@pytest.mark.security
async def test_checkpoint_identity_cannot_cross_a_membership_or_tenant(db: AsyncSession) -> None:
    user, org, *_ = await _world(db)
    await cache.save(
        db, organization_id=org.id, user_id=user.id, key="reading", payload={"fingerprint": "first"}
    )
    await cache.save(
        db,
        organization_id=org.id,
        user_id=user.id,
        key="reading",
        payload={"fingerprint": "second"},
    )
    assert await cache.load(db, organization_id=org.id, user_id=user.id) == {
        "reading": {"fingerprint": "second"}
    }
    assert await cache.load(db, organization_id=uuid4(), user_id=user.id) == {}
    assert len(await cache.for_user(db, user_id=user.id)) == 1
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await cache.save(
                db, organization_id=uuid4(), user_id=user.id, key="reading", payload={}
            )
    await cache.retain(db, organization_id=org.id, user_id=user.id, keys=["reading"])
    assert await cache.load(db, organization_id=org.id, user_id=user.id)
    await cache.erase(db, organization_id=org.id, user_id=user.id)
    assert await cache.load(db, organization_id=org.id, user_id=user.id) == {}


async def test_incremental_read_reuses_committed_index_without_model_calls(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import BaseModel

    from app.schemas.personal_context import ContextDigest, PersonalReading, VerifiedReading
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "Hello"), ("assistant", "How can I help?")])
    await db.commit()
    calls: list[type[BaseModel]] = []

    async def think(self: ProactiveThinker, ctx: object, **kwargs: object) -> BaseModel:
        output = kwargs["output_type"]
        assert isinstance(output, type) and issubclass(output, BaseModel)
        assert output in {ContextDigest, PersonalReading, VerifiedReading}
        calls.append(output)
        return output()

    monkeypatch.setattr(ProactiveThinker, "think", think)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    assert calls == [ContextDigest, PersonalReading]
    assert f"conversation:{conversation.id}" in await cache.load(
        db, organization_id=org.id, user_id=user.id
    )
    calls.clear()
    assert await PersonalLook(db).look(org.id, user.id) == 0
    assert calls == []


async def test_extractor_upgrade_refreshes_conversation_and_segment_checkpoints(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import BaseModel

    from app.schemas.personal_context import ContextDigest, PersonalReading
    from app.services.proactive import _personal as personal
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "I keep losing project follow-ups.")])
    await db.commit()
    calls: list[type[BaseModel]] = []

    async def think(self: ProactiveThinker, ctx: object, **kwargs: object) -> BaseModel:
        output = kwargs["output_type"]
        assert isinstance(output, type) and issubclass(output, BaseModel)
        calls.append(output)
        return output()

    monkeypatch.setattr(ProactiveThinker, "think", think)
    current_version = personal.EXTRACTOR_VERSION
    monkeypatch.setattr(personal, "EXTRACTOR_VERSION", "previous-extractor")
    assert await personal.PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    before = await cache.load(db, organization_id=org.id, user_id=user.id)
    calls.clear()

    monkeypatch.setattr(personal, "EXTRACTOR_VERSION", current_version)
    assert await personal.PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    after = await cache.load(db, organization_id=org.id, user_id=user.id)
    assert calls == [ContextDigest, PersonalReading]
    key = f"conversation:{conversation.id}"
    assert before[key]["revision"] != after[key]["revision"]
    assert before[key]["part_keys"] != after[key]["part_keys"]
    calls.clear()
    assert await personal.PersonalLook(db).look(org.id, user.id) == 0
    assert calls == []


@pytest.mark.security
@pytest.mark.parametrize("change", ["opt_out", "membership", "source_edit", "disabled"])
async def test_source_changes_while_extracting_cannot_write_a_checkpoint(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from app.repositories import member_repo
    from app.schemas.personal_context import ContextDigest
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "Hello"), ("assistant", "Welcome")])
    await db.commit()

    async def changed(self: ProactiveThinker, ctx: object, **kwargs: object) -> ContextDigest:
        if change == "opt_out":
            user.proactive_opt_out = True
        elif change == "disabled":
            org.proactive_enabled = False
        elif change == "membership":
            member = await member_repo.get_active(db, organization_id=org.id, user_id=user.id)
            assert member is not None
            member.role = "viewer"
        else:
            await db.execute(
                text("UPDATE messages SET content = 'Changed' WHERE conversation_id = :id"),
                {"id": conversation.id},
            )
        await db.commit()
        return ContextDigest()

    monkeypatch.setattr(ProactiveThinker, "think", changed)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    assert await cache.load(db, organization_id=org.id, user_id=user.id) == {}


async def test_large_source_resumes_from_committed_segments(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import BaseModel

    from app.schemas.personal_context import ContextDigest, PersonalReading
    from app.services.proactive._context_pipeline import CHUNK_CHARS
    from app.services.proactive._personal import MAX_NEW_CHUNKS, PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "x" * (CHUNK_CHARS * MAX_NEW_CHUNKS + 5))])
    await db.commit()
    stages: list[type[BaseModel]] = []

    async def think(self: ProactiveThinker, ctx: object, **kwargs: object) -> BaseModel:
        output = kwargs["output_type"]
        assert isinstance(output, type) and issubclass(output, BaseModel)
        stages.append(output)
        return output()

    monkeypatch.setattr(ProactiveThinker, "think", think)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    stored = await cache.load(db, organization_id=org.id, user_id=user.id)
    assert len(stored) == MAX_NEW_CHUNKS
    assert stages == [ContextDigest] * MAX_NEW_CHUNKS
    stages.clear()
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    assert stages == [ContextDigest, PersonalReading]
    assert f"conversation:{conversation.id}" in await cache.load(
        db, organization_id=org.id, user_id=user.id
    )


async def test_owned_due_task_can_be_proposed_without_any_new_chat(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.repositories import suggestion_repo
    from app.schemas.personal_context import (
        PersonalAdvice,
        PersonalReading,
        SourceEvidence,
        VerifiedReading,
    )
    from app.schemas.task import TaskCreate, TaskUpdate
    from app.services.proactive._context_snapshot import current_packet
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker
    from app.services.tasks import TaskService

    user, org, agent, _, model, ctx = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    task = await TaskService(db).create(
        ctx, TaskCreate(title="Review the release", due_at=datetime.now(UTC) - timedelta(days=1))
    )
    await db.commit()
    packet = await current_packet(db, ctx, user, now=datetime.now(UTC), starter_id=agent.id)
    assert packet.current_state["due_state"] == {str(task.id): "overdue"}
    proposal = PersonalAdvice(
        identity="review-release",
        kind="task",
        title="Review the release",
        detail="The private task is overdue.",
        chat_prompt="Open my release review task.",
        resource_ids=[str(task.id)],
        evidence=[SourceEvidence(source_id=f"task:{task.id}", quote="Review the release")],
    )

    async def think(
        self: ProactiveThinker, ctx: object, **kwargs: object
    ) -> PersonalReading | VerifiedReading:
        if kwargs["output_type"] is PersonalReading:
            return PersonalReading(opportunities=[proposal], starters=["Review my release task"])
        assert kwargs["output_type"] is VerifiedReading
        return VerifiedReading(
            approved_identities=[proposal.identity], approved_starter_indices=[0]
        )

    monkeypatch.setattr(ProactiveThinker, "think", think)
    assert await PersonalLook(db).look(org.id, user.id) == 1
    await db.commit()
    open_rows = await suggestion_repo.list_open(db, organization_id=org.id, user_id=user.id)
    assert len(open_rows) == 1 and open_rows[0].payload["personal_context"] is True
    assert await suggestion_repo.open_generated_people(db, organization_id=org.id) == {user.id: 1}
    await TaskService(db).update(
        ctx, task.id, TaskUpdate(title=task.title, status="done", expected_revision=task.revision)
    )
    await db.commit()

    async def empty(self: ProactiveThinker, ctx: object, **kwargs: object) -> PersonalReading:
        return PersonalReading()

    monkeypatch.setattr(ProactiveThinker, "think", empty)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    assert await suggestion_repo.list_open(db, organization_id=org.id, user_id=user.id) == []


@pytest.mark.security
@pytest.mark.parametrize(
    "reason", ["missing", "inactive", "opt_out", "disabled", "starter", "membership"]
)
async def test_unavailable_person_or_disabled_role_never_calls_a_model(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, _, model, _ = await _world(db)
    agent.slug = "agenticos" if reason != "starter" else "different"
    org.proactive_enabled = reason != "disabled"
    org.proactive_model_profile_id = model.id
    if reason == "inactive":
        user.is_active = False
    if reason == "opt_out":
        user.proactive_opt_out = True
    if reason == "membership":
        await db.execute(
            text("DELETE FROM organization_members WHERE user_id = :id"), {"id": user.id}
        )
    await db.commit()

    async def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Ineligible personal reads must not call a model")

    monkeypatch.setattr(ProactiveThinker, "think", unexpected)
    assert await PersonalLook(db).look(org.id, uuid4() if reason == "missing" else user.id) == 0


@pytest.mark.security
@pytest.mark.parametrize(
    "change",
    ["opt_out", "membership", "source_edit", "disabled", "profile", "conversation_revoked"],
)
async def test_final_delivery_rechecks_person_source_and_current_state(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from app.repositories import member_repo, suggestion_repo
    from app.schemas.personal_context import ContextDigest, PersonalReading
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "Hello"), ("assistant", "Welcome")])
    await db.commit()

    async def changed(
        self: ProactiveThinker, ctx: object, **kwargs: object
    ) -> ContextDigest | PersonalReading:
        if kwargs["output_type"] is ContextDigest:
            return ContextDigest()
        if change == "opt_out":
            user.proactive_opt_out = True
        elif change == "disabled":
            org.proactive_enabled = False
        elif change == "membership":
            member = await member_repo.get_active(db, organization_id=org.id, user_id=user.id)
            assert member is not None
            member.role = "viewer"
        elif change == "profile":
            user.job_title = "A changed role"
        elif change == "conversation_revoked":
            conversation.user_id = None
        else:
            await db.execute(
                text("UPDATE messages SET content = 'Changed' WHERE conversation_id = :id"),
                {"id": conversation.id},
            )
        await db.commit()
        return PersonalReading()

    monkeypatch.setattr(ProactiveThinker, "think", changed)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    assert await suggestion_repo.list_open(db, organization_id=org.id, user_id=user.id) == []
    assert "reading" not in await cache.load(db, organization_id=org.id, user_id=user.id)


async def test_transcript_pages_keep_first_turn_native_answers_and_call_identity(
    db: AsyncSession,
) -> None:
    import json
    from datetime import UTC, datetime

    from app.db.models.conversation import ToolCall
    from app.services.proactive._personal import PersonalLook

    user, org, agent, version, _, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(
        db,
        conversation,
        run,
        [("user", "First request")] + [("assistant", f"Response {i}") for i in range(101)],
    )
    message = await db.scalar(
        select(Message)
        .where(Message.conversation_id == conversation.id, Message.role == "assistant")
        .order_by(Message.ordinal)
    )
    assert message is not None
    for identity, kind, result in [
        ("ask_user_question", None, json.dumps({"When": ["Thursday 18:00"]})),
        ("native_search", None, "untrusted external body"),
        (None, "generic", "untrusted remote question"),
    ]:
        db.add(
            ToolCall(
                message_id=message.id,
                tool_call_id=str(uuid4()),
                tool_name="Question",
                tool_id=identity,
                presentation_kind=kind,
                args={"questions": [{"header": "When", "question": "When?"}]},
                result=result,
                status="completed",
                started_at=datetime.now(UTC),
            )
        )
    await db.flush()
    turns, receipts = await PersonalLook(db)._turns(
        ctx, conversation, datetime.min.replace(tzinfo=UTC)
    )
    assert turns[0].text == "First request"
    assert len(turns) == 103
    assert any(turn.text == "Thursday 18:00" for turn in turns)
    assert len(receipts) == 2
    assert not any("untrusted" in turn.text for turn in turns)


@pytest.mark.security
async def test_cached_evidence_is_exported_only_while_readable_and_erased_with_memory(
    db: AsyncSession,
) -> None:
    from app.repositories import personal_data_repo
    from app.services.personal_data import PersonalDataService

    user, org, agent, version, *_ = await _world(db)
    _, conversation = await _chat_run(db, org, agent, version, user)
    key = f"conversation:{conversation.id}"
    await cache.save(
        db,
        organization_id=org.id,
        user_id=user.id,
        key=key,
        payload={"quote": "My private context"},
    )
    assert (await PersonalDataService(db)._work_context(user.id))[0]["payload"] == {
        "quote": "My private context"
    }
    row = (await cache.for_user(db, user_id=user.id))[0]
    assert str(user.id) in repr(row)
    conversation.user_id = None
    await db.flush()
    assert await PersonalDataService(db)._work_context(user.id) == []
    await personal_data_repo.forget_briefings_of(db, user.id, organization_id=org.id)
    assert await cache.load(db, organization_id=org.id, user_id=user.id) == {}


@pytest.mark.parametrize("fail_stage", ["extract", "propose"])
async def test_model_refusal_retains_existing_personal_proposals(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, fail_stage: str
) -> None:
    from app.db.models.suggestion import Suggestion, SuggestionKind
    from app.schemas.personal_context import ContextDigest
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "A request")])
    existing = Suggestion(
        organization_id=org.id,
        user_id=user.id,
        kind=SuggestionKind.FINDING.value,
        title="Existing useful proposal",
        detail="Keep me on failure",
        payload={"personal_context": True},
        dedupe_key="keep-on-failure",
    )
    db.add(existing)
    await db.commit()

    async def refuse(self: ProactiveThinker, ctx: object, **kwargs: object) -> ContextDigest | None:
        if fail_stage == "extract" or kwargs["output_type"] is not ContextDigest:
            return None
        return ContextDigest()

    monkeypatch.setattr(ProactiveThinker, "think", refuse)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.refresh(existing)
    assert existing.status == "open" and existing.detail == "Keep me on failure"


async def test_context_cache_migration_round_trips_its_membership_contract(
    db: AsyncSession,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import Connection, inspect

    from app.db.base import Base

    spec = spec_from_file_location(
        "personal_context_migration",
        Path(__file__).parents[2] / "alembic/versions/0349_personal_work_context.py",
    )
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    def round_trip(connection: Connection) -> None:
        with Operations.context(
            MigrationContext.configure(connection, opts={"target_metadata": Base.metadata})
        ):
            migration.downgrade()
            assert "personal_context_cache" not in inspect(connection).get_table_names()
            migration.upgrade()
        reflected = inspect(connection)
        assert {column["name"] for column in reflected.get_columns("personal_context_cache")} == {
            "organization_id",
            "user_id",
            "source_key",
            "payload",
            "created_at",
            "updated_at",
        }
        foreign = reflected.get_foreign_keys("personal_context_cache")
        assert len(foreign) == 1
        assert foreign[0]["referred_table"] == "organization_members"
        assert foreign[0]["options"]["ondelete"] == "CASCADE"

    await (await db.connection()).run_sync(round_trip)


async def test_empty_refused_and_failed_text_does_not_enter_the_index(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from app.db.models.agent_run import RunStatus
    from app.services.proactive._personal import PersonalLook

    user, org, agent, version, _, ctx = await _world(db)
    run, conversation = await _chat_run(
        db, org, agent, version, user, status=RunStatus.FAILED, input_tokens=0
    )
    look = PersonalLook(db)
    assert await look._turns(ctx, conversation, datetime.min.replace(tzinfo=UTC)) == ([], [])
    await _transcript(
        db, conversation, run, [("user", "Refused input"), ("assistant", "No model output")]
    )
    monkeypatch.setattr(PersonalLook, "_past_the_input_edge", AsyncMock(return_value=[]))
    assert await look._turns(ctx, conversation, datetime.min.replace(tzinfo=UTC)) == ([], [])


@pytest.mark.security
@pytest.mark.parametrize("stage", ["checkpoint", "completed_index", "delivery"])
async def test_an_erasure_during_a_read_fences_checkpoints_and_delivery(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from unittest.mock import AsyncMock

    from app.repositories import audit_log_repo
    from app.schemas.personal_context import ContextDigest, PersonalReading
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "A private request")])
    await db.commit()

    async def think(
        self: ProactiveThinker, ctx: object, **kwargs: object
    ) -> ContextDigest | PersonalReading:
        extracting = kwargs["output_type"] is ContextDigest
        if stage == "completed_index" and extracting:
            monkeypatch.setattr(
                audit_log_repo, "memory_erased_since", AsyncMock(side_effect=[False, True])
            )
        if (stage == "checkpoint" and extracting) or (stage == "delivery" and not extracting):
            monkeypatch.setattr(audit_log_repo, "memory_erased_since", AsyncMock(return_value=True))
        return ContextDigest() if extracting else PersonalReading()

    monkeypatch.setattr(ProactiveThinker, "think", think)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    stored = await cache.load(db, organization_id=org.id, user_id=user.id)
    assert "reading" not in stored
    if stage == "checkpoint":
        assert stored == {}


@pytest.mark.security
async def test_a_decision_racing_final_replacement_is_not_lost(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.suggestion import Suggestion, SuggestionKind, SuggestionStatus
    from app.repositories import suggestion_repo
    from app.schemas.personal_context import PersonalReading
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, _, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    existing = Suggestion(
        organization_id=org.id,
        user_id=user.id,
        kind=SuggestionKind.FINDING.value,
        title="Existing",
        detail="A previous suggestion",
        payload={"personal_context": True},
        dedupe_key="racing-decision",
    )
    db.add(existing)
    await db.commit()
    original = suggestion_repo.remove_open_generated

    async def raced(
        session: AsyncSession, *, organization_id: UUID, user_id: UUID, expected_ids: set[UUID]
    ) -> bool:
        await suggestion_repo.decide(
            session, suggestion=existing, status=SuggestionStatus.DISMISSED
        )
        return await original(
            session, organization_id=organization_id, user_id=user_id, expected_ids=expected_ids
        )

    async def reading(*args: object, **kwargs: object) -> PersonalReading:
        return PersonalReading()

    monkeypatch.setattr(ProactiveThinker, "think", reading)
    monkeypatch.setattr(suggestion_repo, "remove_open_generated", raced)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.refresh(existing)
    assert existing.status == "dismissed"


async def test_retained_model_output_remains_indexable_without_a_run_row(db: AsyncSession) -> None:
    from datetime import UTC, datetime

    from app.db.models.agent_run import AgentRun
    from app.services.proactive._personal import PersonalLook

    user, org, agent, version, _, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(
        db,
        conversation,
        run,
        [("user", "A retained request"), ("assistant", "A retained model answer")],
    )
    await db.execute(
        text(
            "UPDATE messages SET model_name = 'retained-model' WHERE conversation_id = :id AND role = 'assistant'"
        ),
        {"id": conversation.id},
    )
    await db.execute(delete(AgentRun).where(AgentRun.id == run.id))
    turns, _ = await PersonalLook(db)._turns(ctx, conversation, datetime.min.replace(tzinfo=UTC))
    assert any(turn.text == "A retained model answer" for turn in turns)


async def test_task_inventory_marks_a_bounded_page_incomplete(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from app.schemas.task import BoardEnsure, TaskCreate, TaskList
    from app.services.proactive._context_snapshot import current_packet
    from app.services.tasks import TaskService

    user, _, agent, _, _, ctx = await _world(db)
    service = TaskService(db)
    task = await service.create(ctx, TaskCreate(title="One private task"))
    await service.ensure_board(ctx, BoardEnsure(scope="organization"))
    page = TaskList(
        items=[task.model_copy(update={"id": uuid4()}) for _ in range(100)], has_more=False
    )
    monkeypatch.setattr(TaskService, "list_tasks", AsyncMock(return_value=page))
    packet = await current_packet(db, ctx, user, now=datetime.now(UTC), starter_id=agent.id)
    tasks = packet.current_state["tasks"]
    assert isinstance(tasks, list) and len(tasks) == 100
    assert packet.current_state["tasks_complete"] is False


async def test_routine_snapshot_keeps_actual_state_and_timezone_fields(db: AsyncSession) -> None:
    from datetime import UTC, datetime

    from app.db.models.agent_trigger import AgentTrigger
    from app.services.proactive._context_snapshot import current_packet

    user, org, agent, _, _, ctx = await _world(db)
    trigger = AgentTrigger(
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        name="Weekly report",
        prompt="Prepare the report",
        next_fire_at=datetime.now(UTC),
        is_active=False,
        schedule_kind="cron",
        cron_expression="0 18 * * 4",
        time_zone="Europe/Warsaw",
    )
    db.add(trigger)
    await db.flush()
    packet = await current_packet(db, ctx, user, now=datetime.now(UTC), starter_id=agent.id)
    rows = packet.current_state["routines"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert isinstance(row, dict)
    assert row["is_active"] is False
    assert row["time_zone"] == "Europe/Warsaw"
    assert isinstance(row["setup_required"], bool)


@pytest.mark.security
@pytest.mark.parametrize(
    "surface", ["api", "embed", "schedule", "workflow", "follow_ups", "a2a", "eval", "proactive"]
)
async def test_automated_inputs_are_not_personal_requests_or_activity(
    db: AsyncSession, surface: str
) -> None:
    from datetime import UTC, datetime

    user, org, agent, version, *_ = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    run.surface = surface
    await _transcript(
        db,
        conversation,
        run,
        [("user", "Automated instruction"), ("assistant", "Automated result")],
    )
    await db.flush()
    assert (
        await cache.transcript_page(
            db,
            organization_id=org.id,
            conversation_id=conversation.id,
            after=-1,
            since=datetime.min.replace(tzinfo=UTC),
        )
        == []
    )
    assert (await cache.usage(db, organization_id=org.id, user_id=user.id, time_zone="UTC"))[
        "active_days"
    ] == 0


@pytest.mark.security
@pytest.mark.parametrize("reason", ["key", "publisher"])
async def test_web_surface_does_not_override_credential_or_publisher_provenance(
    db: AsyncSession, reason: str
) -> None:
    from datetime import UTC, datetime

    user, org, agent, version, *_ = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "An externally submitted request")])
    before = await cache.conversation_revision(
        db, organization_id=org.id, conversation_id=conversation.id
    )
    if reason == "key":
        run.key_scopes = []
    else:
        run.initiated_by_publisher_fallback = True
    await db.flush()
    assert (
        await cache.conversation_revision(
            db, organization_id=org.id, conversation_id=conversation.id
        )
        != before
    )
    assert (
        await cache.transcript_page(
            db,
            organization_id=org.id,
            conversation_id=conversation.id,
            after=-1,
            since=datetime.min.replace(tzinfo=UTC),
        )
        == []
    )


async def test_context_changes_coalesce_and_keep_one_followup_to_an_active_scan(
    db: AsyncSession,
) -> None:
    from app.db.models.background_job import BackgroundJob
    from app.services.proactive import ProactiveService

    user, org, _, _, model, _ = await _world(db)
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    await db.flush()
    service = ProactiveService(db)
    first = await service.queue_context_change(org.id, user.id)
    assert first is not None
    assert await service.queue_context_change(org.id, user.id) is None
    job = await db.get(BackgroundJob, first)
    assert job is not None
    job.status = "running"
    await db.flush()
    followup = await service.queue_context_change(org.id, user.id)
    assert followup is not None and followup != first
    assert await service.queue_context_change(org.id, user.id) is None
    next_job = await db.get(BackgroundJob, followup)
    assert next_job is not None and next_job.concurrency_key == job.concurrency_key


@pytest.mark.security
@pytest.mark.parametrize("change", ["share", "source"])
async def test_delivery_source_locks_hold_access_and_text_until_commit(
    db: AsyncSession, change: str
) -> None:
    from sqlalchemy.exc import DBAPIError

    from app.db.models.conversation_share import ConversationShare

    user, org, agent, version, *_ = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(db, conversation, run, [("user", "A private request")])
    db.add(
        ConversationShare(
            conversation_id=conversation.id,
            shared_with=user.id,
            shared_by=user.id,
            permission="read",
        )
    )
    await db.commit()
    await cache.lock_delivery_sources(
        db, organization_id=org.id, user_id=user.id, conversation_ids=[conversation.id]
    )
    statement = (
        text("DELETE FROM conversation_shares WHERE conversation_id = :id")
        if change == "share"
        else text("UPDATE messages SET content = 'Changed' WHERE conversation_id = :id")
    )
    async with AsyncSession(bind=db.bind) as writer:
        await writer.execute(text("SET LOCAL lock_timeout = '50ms'"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            await writer.execute(statement, {"id": conversation.id})
        await writer.rollback()
        await db.commit()
        await writer.execute(statement, {"id": conversation.id})
        await writer.commit()


@pytest.mark.security
async def test_an_answer_after_erasure_survives_an_older_question_message(db: AsyncSession) -> None:
    import json
    from datetime import UTC, datetime, timedelta

    from app.db.models.conversation import ToolCall
    from app.services.proactive._personal import PersonalLook

    user, org, agent, version, _, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(
        db, conversation, run, [("user", "Forgotten request"), ("assistant", "Forgotten response")]
    )
    fence = datetime.now(UTC)
    message = await db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id, Message.role == "assistant"
        )
    )
    assert message is not None
    await db.execute(
        text("UPDATE messages SET created_at = :old WHERE conversation_id = :id"),
        {"old": fence - timedelta(days=1), "id": conversation.id},
    )
    db.add(
        ToolCall(
            message_id=message.id,
            tool_call_id=str(uuid4()),
            tool_name="Question",
            tool_id="ask_user_question",
            args={"questions": [{"header": "When", "question": "When?"}]},
            result=json.dumps({"When": ["Thursday 18:00"]}),
            status="completed",
            started_at=fence - timedelta(days=1),
            completed_at=fence + timedelta(seconds=1),
        )
    )
    await db.flush()
    db.add(
        ToolCall(
            message_id=message.id,
            tool_call_id=str(uuid4()),
            tool_name="Question",
            tool_id="ask_user_question",
            args={"questions": [{"header": "Old", "question": "Forgotten?"}]},
            result=json.dumps({"Old": ["Forgotten answer"]}),
            status="completed",
            started_at=fence - timedelta(days=1),
            completed_at=fence - timedelta(hours=1),
        )
    )
    await db.flush()
    turns, receipts = await PersonalLook(db)._turns(ctx, conversation, fence)
    assert [turn.text for turn in turns] == ["Thursday 18:00"]
    assert len(receipts) == 1


@pytest.mark.security
async def test_channel_authors_and_identity_changes_never_fall_back_to_thread_owner(
    db: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    from app.db.models.channel_identity import ChannelIdentity
    from app.services.proactive._personal import PersonalLook

    user, org, agent, version, _, ctx = await _world(db)
    colleague, *_ = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    identity = ChannelIdentity(
        platform="slack", platform_user_id=str(uuid4()), user_id=colleague.id, is_active=True
    )
    db.add(identity)
    await db.flush()
    await _transcript(db, conversation, run, [("user", "Please automate my work")])
    await db.execute(
        text("UPDATE messages SET channel_identity_id = :identity WHERE conversation_id = :id"),
        {"identity": identity.id, "id": conversation.id},
    )
    before = await cache.conversation_revision(
        db, organization_id=org.id, conversation_id=conversation.id
    )
    turns, _ = await PersonalLook(db)._turns(ctx, conversation, datetime.min.replace(tzinfo=UTC))
    assert turns[0].speaker_id == str(colleague.id)
    identity.is_active = False
    await db.flush()
    assert before != await cache.conversation_revision(
        db, organization_id=org.id, conversation_id=conversation.id
    )
    turns, _ = await PersonalLook(db)._turns(ctx, conversation, datetime.min.replace(tzinfo=UTC))
    assert turns[0].speaker_id == "unknown"


async def test_extraction_segments_do_not_repeat_a_whole_threads_answer_history(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from datetime import UTC, datetime

    from pydantic import BaseModel

    from app.db.models.conversation import ToolCall
    from app.schemas.personal_context import ContextDigest, PersonalReading
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("assistant", "Questions")])
    message = await db.scalar(select(Message).where(Message.conversation_id == conversation.id))
    assert message is not None
    for index in range(2):
        db.add(
            ToolCall(
                message_id=message.id,
                tool_call_id=str(uuid4()),
                tool_name="Question",
                tool_id="ask_user_question",
                args={"questions": [{"header": "Answer", "question": "Details?"}]},
                result=json.dumps({"Answer": [str(index) + "x" * 10000]}),
                status="completed",
                started_at=datetime.now(UTC),
            )
        )
    await db.commit()
    receipts_per_segment = []

    async def think(self: ProactiveThinker, ctx: object, **kwargs: object) -> BaseModel:
        output = kwargs["output_type"]
        if output is ContextDigest:
            prompt = kwargs["prompt"]
            assert isinstance(prompt, str)
            material = json.loads(prompt)["context"]
            receipts_per_segment.append(len(material["tool_receipts"]))
            return ContextDigest()
        assert output is PersonalReading
        return PersonalReading()

    monkeypatch.setattr(ProactiveThinker, "think", think)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    assert receipts_per_segment == [1, 1]


async def test_an_append_and_an_edit_reuse_unchanged_completed_segments(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import BaseModel

    from app.schemas.personal_context import ContextDigest, PersonalReading
    from app.services.proactive._context_pipeline import CHUNK_CHARS
    from app.services.proactive._personal import PersonalLook
    from app.services.proactive._thinker import ProactiveThinker

    user, org, agent, version, model, _ = await _world(db)
    agent.slug = "agenticos"
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    run, conversation = await _chat_run(db, org, agent, version, user, input_tokens=10)
    await _transcript(db, conversation, run, [("user", "x" * (CHUNK_CHARS * 3 + 200))])
    await db.commit()
    calls = []

    async def think(self: ProactiveThinker, ctx: object, **kwargs: object) -> BaseModel:
        output = kwargs["output_type"]
        assert output in {ContextDigest, PersonalReading}
        calls.append(output)
        return output()

    monkeypatch.setattr(ProactiveThinker, "think", think)
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    assert calls.count(ContextDigest) == 4
    stored = await cache.load(db, organization_id=org.id, user_id=user.id)
    assert not any(key.startswith("part:") for key in stored)
    assert len(stored[f"conversation:{conversation.id}"]["part_keys"]) == 4
    db.add(
        Message(
            conversation_id=conversation.id,
            run_id=run.id,
            role="user",
            content="Also prepare the release agenda",
            ordinal=1,
        )
    )
    await db.commit()
    calls.clear()
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    assert calls.count(ContextDigest) == 1
    original = await db.scalar(
        select(Message).where(Message.conversation_id == conversation.id, Message.ordinal == 0)
    )
    assert original is not None
    original.content = "y" + original.content[1:]
    await db.commit()
    calls.clear()
    assert await PersonalLook(db).look(org.id, user.id) == 0
    await db.commit()
    assert calls.count(ContextDigest) == 1
    assert not any(
        key.startswith("part:")
        for key in await cache.load(db, organization_id=org.id, user_id=user.id)
    )
