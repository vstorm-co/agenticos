"""System agents against Postgres (#2575): configuration, history and the memory extraction job."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.audience import RunAudience
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.locks import LockScope, hold_subject
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import RunStatus, RunSurface
from app.db.models.background_job import BackgroundJob
from app.db.models.conversation import Conversation, Message
from app.db.models.credential import ModelProfile
from app.db.models.memory_claim import MemoryClaim
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.system_agent_profile import DAILY_BRIEFING, MEMORY_MAINTENANCE
from app.db.models.user import User
from app.repositories import agent_run_repo, system_agent_repo
from app.schemas.system_agent import SystemAgentUpdate
from app.services.memory import extraction
from app.services.proactive import _thinker
from app.services.system_agent import SystemAgentService
from app.worker.tasks import memory_tasks
from tests.integration._keys import provider_key

pytestmark = [pytest.mark.anyio, pytest.mark.security]

SPEC = {"capabilities": [{"id": "memory_files", "enabled": True, "config": {}}]}


async def _world(db: AsyncSession, *, spec: dict | None = None):
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    agent = Agent(
        organization_id=org.id,
        name="Finance",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        agent_id=agent.id,
        organization_id=org.id,
        version=1,
        spec=SPEC if spec is None else spec,
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    model = ModelProfile(
        id=uuid.uuid4(),
        organization_id=org.id,
        label="Maintenance model",
        provider="openai",
        model="gpt-4.1",
        secret_id=await provider_key(db, org.id),
    )
    db.add(model)
    await db.flush()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)
    return user, org, agent, version, model, ctx


async def _chat_run(db, org, agent, version, user, *, status=RunStatus.COMPLETED, **overrides):
    conversation = Conversation(organization_id=org.id, user_id=user.id, title="x")
    db.add(conversation)
    await db.flush()
    run = await agent_run_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        user_id=user.id,
        conversation_id=conversation.id,
        surface=RunSurface.WEB.value,
        model_label="m",
        started_at=datetime.now(UTC),
    )
    run.status = status.value
    for key, value in overrides.items():
        setattr(run, key, value)
    await db.flush()
    return run, conversation


async def test_a_profile_is_provisioned_once_and_spends_nothing_until_a_model_is_chosen(
    db: AsyncSession,
) -> None:
    user, org, *_ = await _world(db)

    first = await system_agent_repo.provision(db, organization_id=org.id, role=MEMORY_MAINTENANCE)
    again = await system_agent_repo.provision(db, organization_id=org.id, role=MEMORY_MAINTENANCE)

    assert first.enabled and first.model_profile_id is None and first.role == MEMORY_MAINTENANCE
    assert (again.organization_id, again.role) == (first.organization_id, first.role)


async def test_the_overview_lists_both_roles_with_the_briefing_read_from_proactivity(
    db: AsyncSession,
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    org.proactive_enabled = True
    org.proactive_model_profile_id = model.id
    await db.flush()

    overview = await SystemAgentService(db).overview(ctx)

    briefing, maintenance = overview.items
    assert briefing.role == DAILY_BRIEFING and briefing.managed_in == "proactivity"
    assert briefing.enabled and briefing.model_label == "Maintenance model"
    assert maintenance.role == MEMORY_MAINTENANCE and maintenance.managed_in is None
    assert maintenance.model_profile_id is None and maintenance.runs == []
    assert briefing.unavailable == "starter_agent"
    assert maintenance.unavailable is None, "maintenance uses each originating agent"


async def test_a_published_starter_agent_leaves_the_roles_available(db: AsyncSession) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    agent.slug = "agenticos"
    await db.flush()

    overview = await SystemAgentService(db).overview(ctx)

    assert [item.unavailable for item in overview.items] == [None, None]


async def test_it_is_configured_with_a_model_a_budget_and_a_switch_and_the_change_is_audited(
    db: AsyncSession,
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    service = SystemAgentService(db)

    saved = await service.update(
        ctx,
        MEMORY_MAINTENANCE,
        SystemAgentUpdate(enabled=True, model_profile_id=model.id, monthly_budget_usd=Decimal("5")),
    )

    assert saved.model_label == "Maintenance model" and saved.monthly_budget_usd == Decimal("5")
    off = await service.update(ctx, MEMORY_MAINTENANCE, SystemAgentUpdate(enabled=False))
    assert not off.enabled and off.model_profile_id is None


async def test_it_will_not_run_on_a_default_or_somebody_elses_model_or_the_briefings_role(
    db: AsyncSession,
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    _, other_org, _, _, foreign, _ = await _world(db)
    service = SystemAgentService(db)

    with pytest.raises(BadRequestError, match="Choose the model"):
        await service.update(ctx, MEMORY_MAINTENANCE, SystemAgentUpdate(enabled=True))
    with pytest.raises(BadRequestError, match="not one of this organization"):
        await service.update(
            ctx,
            MEMORY_MAINTENANCE,
            SystemAgentUpdate(enabled=True, model_profile_id=foreign.id),
        )
    with pytest.raises(NotFoundError):
        await service.update(ctx, DAILY_BRIEFING, SystemAgentUpdate(enabled=False))


async def test_it_will_not_run_on_a_model_that_cannot_chat(db: AsyncSession) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    speech = ModelProfile(
        id=uuid.uuid4(),
        organization_id=org.id,
        label="Speech",
        provider="openai",
        model="tts-1",
        secret_id=model.secret_id,
    )
    db.add(speech)
    await db.flush()

    with pytest.raises(BadRequestError):
        await SystemAgentService(db).update(
            ctx,
            MEMORY_MAINTENANCE,
            SystemAgentUpdate(enabled=True, model_profile_id=speech.id),
        )


async def test_its_history_and_spend_are_the_runs_attributed_to_it(db: AsyncSession) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    run, _ = await _chat_run(db, org, agent, version, user)
    run.system_role = MEMORY_MAINTENANCE
    run.cost_usd = Decimal("0.25")
    other, _ = await _chat_run(db, org, agent, version, user)
    other.cost_usd = Decimal("9")
    await db.flush()

    maintenance = (await SystemAgentService(db).overview(ctx)).items[1]

    assert maintenance.spent_this_month == Decimal("0.25")
    assert [item.id for item in maintenance.runs] == [run.id]
    mine = await agent_run_repo.proactive_spend_since(
        db, organization_id=org.id, user_id=user.id, since=datetime(2020, 1, 1, tzinfo=UTC)
    )
    assert mine == 0, "the role's spend is not the person's proactivity limit"


async def _enabled(db, org, model):
    profile = await system_agent_repo.provision(db, organization_id=org.id, role=MEMORY_MAINTENANCE)
    await system_agent_repo.update(
        db, profile, enabled=True, model_profile_id=model.id, monthly_budget_usd=None
    )


async def test_a_finished_chat_is_queued_for_extraction_only_where_the_role_is_on(
    db: AsyncSession,
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    run, _ = await _chat_run(db, org, agent, version, user)

    assert not await extraction.queue_extraction(db, run, SPEC)
    await _enabled(db, org, model)
    assert await extraction.queue_extraction(db, run, SPEC)

    jobs = (
        await db.execute(select(BackgroundJob).where(BackgroundJob.kind == "extract-memory"))
    ).all()
    assert len(jobs) == 1
    assert jobs[0][0].concurrency_key == f"memory-maintenance:{org.id}"


async def test_a_chat_others_read_is_not_read_for_the_persons_memory(db: AsyncSession) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    await _enabled(db, org, model)
    run, _ = await _chat_run(db, org, agent, version, user)

    assert not await extraction.queue_extraction(
        db, run, SPEC, audience=RunAudience(user_id=user.id, shared_transcript=True)
    )
    assert await extraction.queue_extraction(db, run, SPEC, audience=RunAudience(user_id=user.id))


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": RunStatus.FAILED.value},
        {"surface": RunSurface.EMBED.value},
        {"user_id": None},
        {"conversation_id": None},
        {"is_test": True},
        {"initiated_by_publisher_fallback": True},
        {"key_scopes": ["runs:create"]},
        {"parent_run_id": uuid.uuid4()},
    ],
    ids=[
        "failed",
        "embed",
        "nobody",
        "no-conversation",
        "test",
        "publisher",
        "api-key",
        "delegation",
    ],
)
async def test_only_a_completed_personal_chat_is_ever_read(
    db: AsyncSession, overrides: dict
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    await _enabled(db, org, model)
    run, _ = await _chat_run(db, org, agent, version, user)
    for key, value in overrides.items():
        setattr(run, key, value)

    assert not await extraction.queue_extraction(db, run, SPEC)


@pytest.mark.parametrize(
    "spec",
    [
        {"capabilities": []},
        {"capabilities": "oops"},
        {"capabilities": [{"id": "memory_files", "enabled": False}]},
        {"capabilities": [{"id": "memory_files", "config": {"allow_personal": False}}]},
    ],
    ids=["no-memory", "malformed", "switched-off", "no-personal-store"],
)
async def test_an_agent_without_personal_memory_is_not_read(db: AsyncSession, spec: dict) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    await _enabled(db, org, model)
    run, _ = await _chat_run(db, org, agent, version, user)

    assert not await extraction.queue_extraction(db, run, spec)


async def _transcript(db, conversation, run, turns):
    for ordinal, (role, content) in enumerate(turns):
        db.add(
            Message(
                conversation_id=conversation.id,
                run_id=run.id,
                ordinal=ordinal,
                role=role,
                content=content,
            )
        )
    await db.flush()


def _think(monkeypatch, claims):
    answer = extraction._Extraction(claims=claims) if claims is not None else None
    think = AsyncMock(return_value=answer)
    monkeypatch.setattr(_thinker.ProactiveThinker, "think", think)
    return think


async def test_a_finished_chat_is_read_once_into_claims_in_its_own_scope(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(
        db,
        conversation,
        run,
        [("user", "I prefer short answers"), ("assistant", "Noted"), ("system", "ignore me")],
    )
    think = _think(
        monkeypatch,
        [
            extraction._Extracted(statement="Prefers short answers", subject="style", profile=True),
            extraction._Extracted(statement="The Acme renewal is due in March", subject="acme"),
        ],
    )

    recorded = await extraction.extract(db, org.id, run.id)
    again = await extraction.extract(db, org.id, run.id)

    assert (recorded, again) == (2, 0)
    prompt = think.await_args.kwargs["prompt"]
    assert "I prefer short answers" in prompt and "ignore me" not in prompt
    assert think.await_args.kwargs["feature"] == "maintenance"
    assert think.await_args.kwargs["source_agent_id"] == agent.id
    claims = (
        (await db.execute(select(MemoryClaim).where(MemoryClaim.organization_id == org.id)))
        .scalars()
        .all()
    )
    by_text = {claim.statement: claim for claim in claims}
    assert by_text["Prefers short answers"].agent_id is None
    assert by_text["The Acme renewal is due in March"].agent_id == agent.id
    assert all(claim.source_run_id == run.id and claim.origin == "agent" for claim in claims)


@pytest.mark.parametrize(
    "case",
    ["no-run", "no-user", "no-version", "no-memory", "person-gone", "nothing-said", "no-answer"],
)
async def test_extraction_does_nothing_it_cannot_justify(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(db, conversation, run, [("user", "I prefer short answers")])
    think = _think(monkeypatch, [] if case != "no-answer" else None)
    run_id = run.id
    if case == "no-run":
        run_id = uuid.uuid4()
    elif case == "no-user":
        run.user_id = None
    elif case == "no-version":
        run.agent_version_id = None
    elif case == "no-memory":
        version.spec = {"capabilities": []}
    elif case == "person-gone":
        membership = (
            await db.execute(
                select(OrganizationMember).where(OrganizationMember.user_id == user.id)
            )
        ).scalar_one()
        await db.delete(membership)
    elif case == "nothing-said":
        for message in (await db.execute(select(Message))).scalars().all():
            await db.delete(message)
    await db.flush()

    assert await extraction.extract(db, org.id, run_id) == 0
    if case in ("no-run", "no-user", "no-version", "no-memory", "person-gone", "nothing-said"):
        assert not think.await_count


async def test_a_person_with_no_account_left_gets_no_claim(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(db, conversation, run, [("user", "I prefer short answers")])
    _think(monkeypatch, [extraction._Extracted(statement="Prefers short answers")])
    monkeypatch.setattr(extraction, "person_still_exists", AsyncMock(return_value=False))

    assert await extraction.extract(db, org.id, run.id) == 0


async def test_the_job_reads_one_run_in_its_own_session(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from app.worker.jobs import ExtractMemory

    @asynccontextmanager
    async def reuse():
        yield db

    monkeypatch.setattr(memory_tasks, "get_db_context", reuse)
    read = AsyncMock(return_value=3)
    monkeypatch.setattr(memory_tasks.extraction, "extract", read)
    org_id, run_id = uuid.uuid4(), uuid.uuid4()

    assert (
        await memory_tasks.extract_memory(ExtractMemory(organization_id=org_id, run_id=run_id)) == 3
    )
    read.assert_awaited_once_with(db, org_id, run_id)


@pytest.mark.parametrize("moved", ["project", "edit share"])
async def test_a_chat_others_read_by_the_time_the_job_runs_records_nothing(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, moved: str
) -> None:
    from app.db.models.conversation_share import ConversationShare
    from app.db.models.organization import OrganizationMember
    from app.db.models.project import Project

    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(db, conversation, run, [("user", "I prefer short answers")])
    think = _think(monkeypatch, [extraction._Extracted(statement="Prefers short answers")])
    if moved == "project":
        project = Project(organization_id=org.id, owner_user_id=user.id, name="Launch")
        db.add(project)
        await db.flush()
        conversation.project_id = project.id
    else:
        colleague = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(colleague)
        await db.flush()
        db.add(OrganizationMember(organization_id=org.id, user_id=colleague.id, role="member"))
        db.add(
            ConversationShare(
                conversation_id=conversation.id,
                shared_by=user.id,
                shared_with=colleague.id,
                permission="edit",
            )
        )
    await db.flush()

    assert await extraction.extract(db, org.id, run.id) == 0
    assert not think.await_count


async def test_a_chat_shared_during_the_model_call_records_nothing(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.project import Project

    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(db, conversation, run, [("user", "I prefer short answers")])
    found = extraction._Extraction(claims=[extraction._Extracted(statement="Prefers short")])

    async def moved_meanwhile(*args, **kwargs):
        project = Project(organization_id=org.id, owner_user_id=user.id, name="Launch")
        db.add(project)
        await db.flush()
        conversation.project_id = project.id
        await db.flush()
        return found

    monkeypatch.setattr(_thinker.ProactiveThinker, "think", moved_meanwhile)

    assert await extraction.extract(db, org.id, run.id) == 0


async def test_a_chat_read_after_its_person_was_forgotten_records_nothing(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.audit import record_audit

    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    run.ended_at = datetime(2020, 1, 1, tzinfo=UTC)
    await _transcript(db, conversation, run, [("user", "I prefer short answers")])
    think = _think(monkeypatch, [extraction._Extracted(statement="Prefers short answers")])
    await record_audit(
        db,
        actor_user_id=user.id,
        organization_id=org.id,
        action="memory.person.forgotten",
        target_type="user",
        target_id=str(user.id),
        details={},
    )

    assert await extraction.extract(db, org.id, run.id) == 0
    assert not think.await_count, "no model is paid to read what must not be kept"


async def test_an_erasure_made_while_the_run_was_still_going_is_not_read_past(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.audit import record_audit

    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    run.started_at = datetime(2020, 1, 1, tzinfo=UTC)
    run.ended_at = datetime.now(UTC) + timedelta(hours=1)
    await _transcript(db, conversation, run, [("user", "I prefer short answers")])
    think = _think(monkeypatch, [extraction._Extracted(statement="Prefers short answers")])
    await record_audit(
        db,
        actor_user_id=user.id,
        organization_id=org.id,
        action="memory.person.forgotten",
        target_type="user",
        target_id=str(user.id),
        details={},
    )

    assert await extraction.extract(db, org.id, run.id) == 0
    assert not think.await_count


async def test_a_chat_read_after_its_agent_was_cleared_records_nothing(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.audit import record_audit

    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    run.ended_at = datetime(2020, 1, 1, tzinfo=UTC)
    await _transcript(db, conversation, run, [("user", "I prefer short answers")])
    _think(monkeypatch, [extraction._Extracted(statement="Prefers short answers")])
    await record_audit(
        db,
        actor_user_id=user.id,
        organization_id=org.id,
        action="memory.agent.cleared",
        target_type="agent",
        target_id=str(agent.id),
        details={},
    )

    assert await extraction.extract(db, org.id, run.id) == 0


async def test_an_erasure_that_lands_while_the_model_is_answering_still_wins(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.audit import record_audit

    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    run.ended_at = datetime(2020, 1, 1, tzinfo=UTC)
    await _transcript(db, conversation, run, [("user", "I prefer short answers")])

    async def forgotten_meanwhile(*args, **kwargs):
        await record_audit(
            db,
            actor_user_id=user.id,
            organization_id=org.id,
            action="memory.person.forgotten",
            target_type="user",
            target_id=str(user.id),
            details={},
        )
        return extraction._Extraction(claims=[extraction._Extracted(statement="Prefers short")])

    monkeypatch.setattr(_thinker.ProactiveThinker, "think", forgotten_meanwhile)
    # The first check is before the call, and sees nothing yet.
    assert await extraction.extract(db, org.id, run.id) == 0
    claims = (await db.execute(select(MemoryClaim))).scalars().all()
    assert claims == []


@pytest.mark.parametrize("room", [False, True])
async def test_channel_capture_preserves_the_admitted_audience(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    room: bool,
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    await _enabled(db, org, model)
    run, conversation = await _chat_run(
        db, org, agent, version, user, surface=RunSurface.SLACK.value
    )
    await _transcript(db, conversation, run, [("user", "We decided to renew Acme in March")])
    audience = RunAudience(user_id=user.id, room_key="room:slack:C123" if room else None)
    _think(
        monkeypatch,
        [extraction._Extracted(statement="Acme renews in March", kind="decision", profile=True)],
    )
    assert not await extraction.queue_extraction(db, run, SPEC), (
        "legacy jobs cannot guess a channel audience"
    )
    assert await extraction.queue_extraction(db, run, SPEC, audience=audience)
    assert await extraction.extract(db, org.id, run.id, audience=audience) == 1
    claim = await db.scalar(select(MemoryClaim).where(MemoryClaim.source_run_id == run.id))
    assert claim is not None
    assert claim.scope_key == ("room:slack:C123" if room else f"person:{user.id}")
    assert claim.agent_id == (agent.id if room else None)
    assert claim.kind == "decision"
    job = await db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "extract-memory"))
    assert job is not None
    assert job.payload["audience_user_id"] == str(user.id)
    assert job.payload["audience_room_key"] == audience.room_key


async def test_a_group_chat_shared_to_edit_still_records_the_rooms_claims(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models.conversation_share import ConversationShare
    from app.db.models.organization import OrganizationMember

    user, org, agent, version, model, ctx = await _world(db)
    await _enabled(db, org, model)
    run, conversation = await _chat_run(
        db, org, agent, version, user, surface=RunSurface.SLACK.value
    )
    await _transcript(db, conversation, run, [("user", "We decided to renew Acme in March")])
    colleague = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(colleague)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=colleague.id, role="member"))
    db.add(
        ConversationShare(
            conversation_id=conversation.id,
            shared_by=user.id,
            shared_with=colleague.id,
            permission="edit",
        )
    )
    await db.flush()
    audience = RunAudience(user_id=user.id, room_key="room:slack:C123", shared_transcript=True)
    _think(monkeypatch, [extraction._Extracted(statement="Acme renews in March")])

    assert await extraction.queue_extraction(db, run, SPEC, audience=audience)
    assert await extraction.extract(db, org.id, run.id, audience=audience) == 1
    claim = await db.scalar(select(MemoryClaim).where(MemoryClaim.source_run_id == run.id))
    assert claim is not None and claim.scope_key == "room:slack:C123"


@pytest.mark.parametrize("case", ["wrong-person", "read-only", "failed", "key", "test", "embed"])
async def test_capture_refusals_are_rechecked_by_the_worker(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(db, conversation, run, [("user", "Remember me")])
    audience = RunAudience(
        user_id=uuid.uuid4() if case == "wrong-person" else user.id,
        writes_memory=case != "read-only",
    )
    if case == "failed":
        run.status = RunStatus.FAILED.value
    if case == "key":
        run.key_scopes = ["agents:run"]
    if case == "test":
        run.is_test = True
    if case == "embed":
        run.surface = RunSurface.EMBED.value
    await db.flush()
    think = _think(monkeypatch, [extraction._Extracted(statement="Prefers tea")])
    assert not await extraction.queue_extraction(db, run, SPEC, audience=audience)
    assert await extraction.extract(db, org.id, run.id, audience=audience) == 0
    think.assert_not_awaited()


async def test_erasure_committing_while_capture_waits_for_its_write_lock_wins(
    db: AsyncSession,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.memory import MemoryService

    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(db, conversation, run, [("user", "I prefer tea")])
    await db.commit()
    model_reading, erasure_ready, writer_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def answer(*args: object, **kwargs: object) -> extraction._Extraction:
        model_reading.set()
        await erasure_ready.wait()
        return extraction._Extraction(claims=[extraction._Extracted(statement="Prefers tea")])

    async def write_lock(session: AsyncSession, scope: LockScope, person: uuid.UUID) -> None:
        writer_waiting.set()
        await hold_subject(session, scope, person)

    original_exists = extraction.person_still_exists

    async def exists(session: AsyncSession, key: str) -> bool:
        writer_waiting.set()
        return await original_exists(session, key)

    monkeypatch.setattr(_thinker.ProactiveThinker, "think", answer)
    monkeypatch.setattr(extraction, "hold_subject", write_lock, raising=False)
    monkeypatch.setattr(extraction, "person_still_exists", exists)

    async def erase() -> None:
        await model_reading.wait()
        async with sessions() as session:
            await hold_subject(session, LockScope.PERSONAL_DATA_PER_USER, user.id)
            await MemoryService(session).forget_person(ctx, user.id)
            erasure_ready.set()
            await writer_waiting.wait()
            await session.commit()

    async def capture() -> None:
        async with sessions() as session:
            assert await extraction.extract(session, org.id, run.id) == 0
            await session.commit()

    async with asyncio.timeout(20), asyncio.TaskGroup() as tasks:
        tasks.create_task(erase())
        tasks.create_task(capture())
    assert await db.scalar(select(MemoryClaim).where(MemoryClaim.source_run_id == run.id)) is None


async def test_the_worker_preserves_a_room_audience(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from app.worker.jobs import ExtractMemory

    @asynccontextmanager
    async def reuse():
        yield db

    monkeypatch.setattr(memory_tasks, "get_db_context", reuse)
    read = AsyncMock(return_value=1)
    monkeypatch.setattr(memory_tasks.extraction, "extract", read)
    org_id, run_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    payload = ExtractMemory(
        organization_id=org_id,
        run_id=run_id,
        audience_user_id=user_id,
        audience_room_key="room:slack:C123",
    )
    assert await memory_tasks.extract_memory(payload) == 1
    read.assert_awaited_once_with(
        db, org_id, run_id, audience=RunAudience(user_id=user_id, room_key="room:slack:C123")
    )


def test_a_room_capture_job_cannot_drop_its_admitted_person() -> None:
    from pydantic import ValidationError

    from app.worker.jobs import ExtractMemory

    with pytest.raises(ValidationError, match="admitted person"):
        ExtractMemory(
            organization_id=uuid.uuid4(), run_id=uuid.uuid4(), audience_room_key="room:slack:C123"
        )


async def test_membership_removed_during_extraction_prevents_writing(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(db, conversation, run, [("user", "I prefer tea")])

    async def answer(*args: object, **kwargs: object) -> extraction._Extraction:
        member = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org.id,
                OrganizationMember.user_id == user.id,
            )
        )
        assert member is not None
        await db.delete(member)
        await db.flush()
        return extraction._Extraction(claims=[extraction._Extracted(statement="Prefers tea")])

    monkeypatch.setattr(_thinker.ProactiveThinker, "think", answer)
    assert await extraction.extract(db, org.id, run.id) == 0
    assert await db.scalar(select(MemoryClaim).where(MemoryClaim.source_run_id == run.id)) is None


async def test_memory_extraction_reads_the_end_of_a_long_run_in_chronological_order(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, agent, version, model, ctx = await _world(db)
    run, conversation = await _chat_run(db, org, agent, version, user)
    await _transcript(
        db, conversation, run, [("user", f"Fact number {index:03d}") for index in range(75)]
    )
    think = _think(monkeypatch, [])
    assert await extraction.extract(db, org.id, run.id) == 0
    prompt = think.await_args.kwargs["prompt"]
    assert "Fact number 000" not in prompt
    assert "Fact number 014" not in prompt
    assert "Fact number 015" in prompt
    assert "Fact number 074" in prompt
    assert prompt.index("Fact number 015") < prompt.index("Fact number 074")


async def test_removing_a_maintenance_model_disables_its_role(db: AsyncSession) -> None:
    from app.services.model_profile import ModelProfileService

    _, org, _, _, model, ctx = await _world(db)
    await SystemAgentService(db).update(
        ctx,
        MEMORY_MAINTENANCE,
        SystemAgentUpdate(
            enabled=True,
            model_profile_id=model.id,
        ),
    )
    await ModelProfileService(db).delete_profile(ctx, model.id)
    profile = await system_agent_repo.get(db, organization_id=org.id, role=MEMORY_MAINTENANCE)
    assert profile is not None and profile.enabled is False and profile.model_profile_id is None
