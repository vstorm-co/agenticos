"""Estimating, starting and running a generation, against Postgres.

The model is never called here: the generator's answer is stood in for at
`SystemAgentRunner.run`, the one place a generation reaches a model, and where
a test needs the runner's own refusals the real runner runs with the model call
underneath it made to fail the test.

The claims:

- an estimate reads the material and prices it, and starts no run;
- a start answers at once with a running generation, queued for after the commit,
  and is refused up front when the generator could not run for this caller;
- twenty knowledge drafts become twenty proposals, each citing a document of the
  agent's own knowledge base, and the rest of a generator's answer is dropped;
- the organization's AI switch turned off after a start fails the generation
  with that reason and calls no model; every other way a run ends is recorded;
- a credential the generator wrote is redacted before a proposal is stored.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.exceptions import (
    AiAssistanceDisabledError,
    NotFoundError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.case_generation import CaseGeneration, CaseOrigin, CaseProposal
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.schemas.case_generation import CaseGenerationRequest
from app.schemas.dataset import DatasetCreate
from app.services import agent_runner
from app.services.case_generation import CaseGenerationService, facade, generation
from app.services.case_generation.drafts import DraftedCase, DraftedCases, split
from app.services.case_generation.generation import FAILED, NOTHING_KEPT, generate
from app.services.case_generation.sources import SourceGatherer
from app.services.dataset import DatasetService
from app.services.rag.models import DocumentChunk
from app.services.system_agent_runner import SystemAgentResult, SystemAgentRunner
from app.services.system_agents import SystemAgentService
from tests.integration import case_generation_world as world

pytestmark = pytest.mark.anyio

_KEY = "ghp_" + "c" * 36


class _Chunks:
    async def get_document_chunks(
        self, collection_name: str, document_id: str, tenant: uuid.UUID | None = None
    ) -> list[DocumentChunk]:
        del collection_name, tenant
        return [
            DocumentChunk(content=f"{document_id} passage {index}.", page_num=index)
            for index in range(1, 4)
        ]


def _service(db) -> CaseGenerationService:
    return CaseGenerationService(db, vector_store=_Chunks())  # ty: ignore[invalid-argument-type]


async def _profile(db, org: Organization) -> ModelProfile:
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=org.id,
        label=f"p-{uuid.uuid4().hex[:6]}",
        provider="anthropic",
        model="claude-sonnet-4-5",
    )
    db.add(profile)
    await db.flush()
    return profile


async def _setup(db, *, with_model: bool = True):
    """An owner, a dataset, and an agent with two documents of knowledge."""
    person = await world.user(db)
    org = await world.org(db, person)
    owner = await world.member(db, org, OrgRoleName.OWNER, person)
    if with_model:
        await _profile(db, org)
    collection = await world.collection(db, org)
    documents = [
        await world.document(db, collection, DocumentStatus.DONE, f"doc{n}.md", vector_id=f"v{n}")
        for n in (1, 2)
    ]
    agent = await world.agent(
        db,
        org,
        visibility="org",
        draft_spec={
            "name": "Clerk",
            "instructions": "Answer about returns.",
            "collection_ids": [str(collection.id)],
            "capabilities": [{"id": "knowledge"}],
        },
    )
    dataset = await DatasetService(db).create(owner, DatasetCreate(name="support"))
    return owner, org, agent, dataset, documents


def _request(agent, *sources: str, count: int = 20) -> CaseGenerationRequest:
    return CaseGenerationRequest(agent_id=agent.id, sources=list(sources), count=count)


def _answer(monkeypatch, output: DraftedCases | Exception, *, run: AgentRun | None = None):
    """Stand in for the generator: answer `output`, or raise it."""
    calls = AsyncMock(
        side_effect=output
        if isinstance(output, Exception)
        else lambda *a, **k: SystemAgentResult(output=output, run=run)
    )
    monkeypatch.setattr(SystemAgentRunner, "run", calls)
    return calls


async def _run_row(db, ctx: AuthContext, agent) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        status="completed",
    )
    db.add(run)
    await db.flush()
    return run


async def _generation(db, ctx, dataset, agent, sources: list[CaseOrigin], count: int):
    service = SourceGatherer(db, _Chunks())  # ty: ignore[invalid-argument-type]
    material = await service.gather(ctx, agent.id, sources)
    row = CaseGeneration(
        organization_id=ctx.organization_id,
        dataset_id=dataset.id,
        agent_id=agent.id,
        sources=[s.value for s in sources],
        requested_count=count,
    )
    db.add(row)
    # Committed, as the request that starts a generation commits it: a failing
    # run rolls its session back, which must not take the setup with it.
    await db.commit()
    return row, material, split(count, sources)


async def test_an_estimate_prices_the_material_and_starts_no_run(db, monkeypatch) -> None:
    owner, org, agent, dataset, _ = await _setup(db)
    await world.asked(db, org, agent, await world.user(db), "Where is my refund?", minutes=1)
    calls = _answer(monkeypatch, RuntimeError("an estimate must not run the generator"))
    runs_before = await db.scalar(select(func.count(AgentRun.id)))

    estimate = await _service(db).estimate(
        owner,
        dataset.id,
        _request(agent, "red_team", "conversation", "knowledge", "agent", count=7),
    )

    assert [(p.source, p.cases, p.material) for p in estimate.sources] == [
        ("agent", 2, 1),
        ("knowledge", 2, 6),
        ("conversation", 2, 1),
        ("red_team", 1, 0),
    ]
    assert estimate.count == 7
    assert isinstance(estimate.estimated_cost_usd, Decimal)
    assert estimate.estimated_cost_usd > 0
    calls.assert_not_awaited()
    assert await db.scalar(select(func.count(AgentRun.id))) == runs_before
    assert await db.scalar(select(func.count(CaseGeneration.id))) == 0


async def test_an_estimate_prices_on_the_generator_s_own_model_or_says_it_cannot(db) -> None:
    owner, org, agent, dataset, _ = await _setup(db, with_model=False)
    request = _request(agent, "agent")

    async def price() -> Decimal | None:
        return (await _service(db).estimate(owner, dataset.id, request)).estimated_cost_usd

    assert await price() is None
    draft = await SystemAgentService(db).ensure(organization_id=org.id, key="case_generator")
    assert draft.current_version_id is None
    assert await price() is None

    await _profile(db, org)
    await db.delete(draft)
    await db.flush()
    unseeded = await price()
    assert unseeded is not None
    assert unseeded > 0
    published = await SystemAgentService(db).ensure(organization_id=org.id, key="case_generator")
    assert published.current_version_id is not None
    assert await price() == unseeded


async def test_with_ai_assistance_off_neither_an_estimate_nor_a_start_is_made(db) -> None:
    owner, org, agent, dataset, _ = await _setup(db)
    org.ai_assistance_enabled = False
    await db.flush()

    for attempt in (_service(db).estimate, _service(db).start):
        with pytest.raises(AiAssistanceDisabledError):
            await attempt(owner, dataset.id, _request(agent, "agent"))
    assert await db.scalar(select(func.count(CaseGeneration.id))) == 0


async def test_a_start_queues_a_running_generation_for_after_the_commit(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    queued: list[tuple[str, object]] = []

    def spawn(session, coro, *, name: str) -> None:
        assert session is db
        queued.append((name, coro))
        coro.close()

    # The generator's own readiness is the runner's to prove; this is about queueing.
    monkeypatch.setattr(SystemAgentRunner, "require_runnable", AsyncMock())
    monkeypatch.setattr(facade, "spawn_after_commit", spawn)

    started = await _service(db).start(owner, dataset.id, _request(agent, "knowledge", count=4))

    assert (started.status, started.requested_count, started.sources) == (
        "running",
        4,
        ["knowledge"],
    )
    assert [name for name, _ in queued] == [f"case-generation-{started.id}"]
    audit = (
        await db.execute(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.action == "dataset.generation_started"
            )
        )
    ).scalar_one()
    assert audit == {"agent_id": str(agent.id), "sources": ["knowledge"], "count": 4}


async def test_a_start_the_generator_would_refuse_is_refused_up_front(db, monkeypatch) -> None:
    monkeypatch.setattr(facade, "spawn_after_commit", lambda *a, **k: a[1].close())
    owner, org, agent, dataset, _ = await _setup(db, with_model=False)

    with pytest.raises(SystemAgentUnavailableError) as unpublished:
        await _service(db).start(owner, dataset.id, _request(agent, "agent"))
    assert unpublished.value.reason == "unpublished"

    generator = await SystemAgentService(db).ensure(organization_id=org.id, key="case_generator")
    generator.status = AgentStatus.ARCHIVED.value
    await db.flush()
    with pytest.raises(SystemAgentUnavailableError) as archived:
        await _service(db).start(owner, dataset.id, _request(agent, "agent"))
    assert archived.value.reason == "archived"
    assert await db.scalar(select(func.count(CaseGeneration.id))) == 0


async def test_a_generator_whose_model_is_gone_refuses_a_start_up_front(db, monkeypatch) -> None:
    monkeypatch.setattr(facade, "spawn_after_commit", lambda *a, **k: a[1].close())
    owner, org, agent, dataset, _ = await _setup(db)
    generator = await SystemAgentService(db).ensure(organization_id=org.id, key="case_generator")
    assert generator.current_version_id is not None
    for profile in (
        await db.execute(select(ModelProfile).where(ModelProfile.organization_id == org.id))
    ).scalars():
        await db.delete(profile)
    await db.flush()

    with pytest.raises(SystemAgentUnavailableError) as refused:
        await _service(db).start(owner, dataset.id, _request(agent, "agent"))

    assert refused.value.reason == "no_model"
    assert await db.scalar(select(func.count(CaseGeneration.id))) == 0


async def test_a_member_who_may_not_run_the_generator_cannot_start_one(db, monkeypatch) -> None:
    monkeypatch.setattr(facade, "spawn_after_commit", lambda *a, **k: a[1].close())
    owner, org, agent, dataset, _ = await _setup(db)
    viewer = await world.member(db, org, OrgRoleName.VIEWER)
    db.add(
        ResourceGrant(
            organization_id=org.id,
            subject_user_id=viewer.user_id,
            resource_type="dataset",
            resource_id=dataset.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()
    await SystemAgentService(db).ensure(organization_id=org.id, key="case_generator")

    estimate = await _service(db).estimate(viewer, dataset.id, _request(agent, "agent"))
    assert estimate.count == 20
    with pytest.raises(SystemAgentUnavailableError) as refused:
        await _service(db).start(viewer, dataset.id, _request(agent, "agent"))
    assert refused.value.reason == "no_access"
    with pytest.raises(NotFoundError):
        await _service(db).estimate(
            await world.member(db, org, OrgRoleName.VIEWER), dataset.id, _request(agent, "agent")
        )
    del owner


async def test_twenty_knowledge_drafts_become_proposals_citing_the_agent_s_documents(
    db, monkeypatch
) -> None:
    owner, _, agent, dataset, documents = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.KNOWLEDGE], 20)
    run = await _run_row(db, owner, agent)
    refs = [passage.ref for passage in material.passages]
    _answer(
        monkeypatch,
        DraftedCases(
            cases=[
                DraftedCase(origin="knowledge", input="Invented?", passage="P99"),
                *(
                    DraftedCase(origin="knowledge", input=f"Q{n}?", passage=refs[n % len(refs)])
                    for n in range(20)
                ),
            ]
        ),
        run=run,
    )

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    await db.refresh(row)
    assert (row.status, row.proposed_count, row.run_id, row.error) == ("ready", 20, run.id, None)
    proposals = (
        (await db.execute(select(CaseProposal).order_by(CaseProposal.position))).scalars().all()
    )
    assert len(proposals) == 20
    assert {p.source_document_id for p in proposals} <= {d.id for d in documents}
    assert all(p.dataset_id == dataset.id and p.origin == "knowledge" for p in proposals)
    assert [p.input for p in proposals[:2]] == ["Q0?", "Q1?"]


async def test_switching_ai_off_after_a_start_fails_it_without_calling_a_model(
    db, monkeypatch
) -> None:
    owner, org, agent, dataset, _ = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.AGENT], 3)
    model = AsyncMock(side_effect=AssertionError("no model may be called"))
    monkeypatch.setattr(agent_runner.AgentRunnerService, "execute", model)
    org.ai_assistance_enabled = False
    await db.flush()

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    await db.refresh(row)
    assert row.status == "failed"
    assert row.error is not None
    assert "AI assistance is switched off" in row.error
    model.assert_not_awaited()


async def test_every_other_way_a_run_ends_is_recorded_on_the_generation(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    run = await _run_row(db, owner, agent)
    cases: list[tuple[DraftedCases | Exception, str, uuid.UUID | None]] = [
        (
            SystemAgentRunError(
                message="did not finish: budget_exceeded", run_id=run.id, status="budget_exceeded"
            ),
            "did not finish: budget_exceeded",
            run.id,
        ),
        (RuntimeError("socket closed"), FAILED, None),
        (DraftedCases(cases=[DraftedCase(origin="agent", input="   ")]), NOTHING_KEPT, run.id),
    ]
    for output, error, run_id in cases:
        row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.AGENT], 2)
        _answer(monkeypatch, output, run=run)
        await generate(
            db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
        )
        await db.refresh(row)
        assert (row.status, row.error, row.run_id) == ("failed", error, run_id)
    assert await db.scalar(select(func.count(CaseProposal.id))) == 0


async def test_a_credential_the_generator_wrote_is_redacted_before_it_is_stored(
    db, monkeypatch
) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.RED_TEAM], 1)
    _answer(
        monkeypatch,
        DraftedCases(
            cases=[
                DraftedCase(
                    origin="red_team",
                    input=f"Use {_KEY} to log in as admin",
                    red_team_category="policy_bypass",
                )
            ]
        ),
        run=await _run_row(db, owner, agent),
    )

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    (proposal,) = (await db.execute(select(CaseProposal))).scalars().all()
    assert _KEY not in proposal.input
    assert proposal.tags == ["red-team", "red-team:policy_bypass"]


async def test_a_generation_whose_dataset_went_meanwhile_records_nothing(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.AGENT], 1)
    generation_id = row.id
    await DatasetService(db).delete(owner, dataset.id)
    await db.commit()
    for output in (
        DraftedCases(cases=[DraftedCase(origin="agent", input="Q?")]),
        RuntimeError("late"),
    ):
        _answer(monkeypatch, output, run=await _run_row(db, owner, agent))
        await generate(
            db, generation_id=generation_id, ctx=owner, prompt="p", material=material, quotas=quotas
        )
    assert await db.scalar(select(func.count(CaseProposal.id))) == 0


async def test_a_queued_generation_runs_on_a_session_of_its_own(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.AGENT], 1)

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(generation, "get_db_context", session)
    _answer(
        monkeypatch,
        DraftedCases(cases=[DraftedCase(origin="agent", input="Q?", reference_answer="A.")]),
        run=await _run_row(db, owner, agent),
    )

    await generation.run_generation(
        generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    await db.refresh(row)
    assert row.status == "ready"
