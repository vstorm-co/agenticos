"""System agents against Postgres (#2575): configuration, history and the memory extraction job."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
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
