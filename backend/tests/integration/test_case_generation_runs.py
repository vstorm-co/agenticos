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
  with that reason and calls no model; every other way a run ends is recorded,
  an unreadable answer keeps why on the run, and a source deleted meanwhile
  fails the generation rather than leaving it running;
- a credential the generator wrote is redacted before a proposal is stored.
"""

import json
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    AiAssistanceDisabledError,
    BadRequestError,
    NotFoundError,
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.background_job import BackgroundJob
from app.db.models.case_generation import CaseGeneration, CaseOrigin, CaseProposal
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.db.models.user import User
from app.repositories import agent_run_repo, project_repo
from app.schemas.case_generation import CaseGenerationRequest
from app.schemas.change_event import ChangeEvent
from app.schemas.dataset import DatasetCreate
from app.services import agent_runner, change_feed
from app.services.case_generation import CaseGenerationService, worker
from app.services.case_generation.drafts import DraftedCase, DraftedCases, split
from app.services.case_generation.generation import FAILED, NOTHING_KEPT, generate
from app.services.case_generation.sources import SourceGatherer
from app.services.case_generation.worker import CaseGenerationWorker
from app.services.dataset import DatasetService
from app.services.rag.models import DocumentChunk
from app.services.system_agent_runner import SystemAgentResult, SystemAgentRunner
from app.services.system_agents import SystemAgentService
from app.worker.handlers import settle_ended
from app.worker.jobs import GenerateCases
from app.worker.tasks import case_generation_tasks
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


async def test_a_start_queues_a_running_generation_as_a_job(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    # The generator's own readiness is the runner's to prove; this is about queueing.
    monkeypatch.setattr(SystemAgentRunner, "require_runnable", AsyncMock())

    started = await _service(db).start(owner, dataset.id, _request(agent, "knowledge", count=4))

    assert (started.status, started.requested_count, started.sources) == (
        "running",
        4,
        ["knowledge"],
    )
    job = (await db.execute(select(BackgroundJob))).scalar_one()
    assert (job.kind, job.payload, job.organization_id) == (
        "generate-cases",
        {"generation_id": str(started.id), "organization_id": str(owner.organization_id)},
        owner.organization_id,
    )
    row = await db.get(CaseGeneration, started.id)
    assert row is not None and row.auto_accept is False
    audit = (
        await db.execute(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.action == "dataset.generation_started"
            )
        )
    ).scalar_one()
    assert audit == {
        "agent_id": str(agent.id),
        "sources": ["knowledge"],
        "count": 4,
        "auto_accept": False,
    }


async def test_a_start_the_generator_would_refuse_is_refused_up_front(db, monkeypatch) -> None:
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


async def test_an_unreadable_answer_keeps_why_on_the_generator_s_run(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.AGENT], 1)
    run = await _run_row(db, owner, agent)

    async def unreadable(*args, **kwargs) -> None:
        await agent_run_repo.set_error(db, run=run, error="Not valid JSON")
        raise SystemAgentOutputError(message="could not be read", run_id=run.id, answer="?")

    monkeypatch.setattr(SystemAgentRunner, "run", unreadable)

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    await db.refresh(row)
    await db.refresh(run)
    assert (row.status, row.error, row.run_id) == ("failed", "could not be read", run.id)
    assert run.error == "Not valid JSON"


def _model_answers(monkeypatch, agent, run: AgentRun, cases: list[dict]) -> None:
    """Stand in for the model under the real runner, which reads the answer itself."""
    monkeypatch.setattr(SystemAgentRunner, "require_runnable", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        agent_runner.AgentRunnerService,
        "execute",
        AsyncMock(return_value=(json.dumps({"cases": cases}), run)),
    )


_READABLE = {"origin": "agent", "input": "Can I return shoes?", "reference_answer": "Yes."}
_MALFORMED = {"origin": "agent", "input": "And boots?", "expected_tools": "lookup_order"}


async def test_cases_that_could_not_be_read_are_left_out_and_counted(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.AGENT], 4)
    run = await _run_row(db, owner, agent)
    _model_answers(
        monkeypatch,
        agent,
        run,
        [_READABLE, _MALFORMED, {**_READABLE, "input": "Can I return a hat?"}, _MALFORMED],
    )

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    await db.refresh(row)
    assert (row.status, row.proposed_count, row.unreadable_count, row.rejected_count) == (
        "ready",
        2,
        2,
        0,
    )
    proposals = (
        (await db.execute(select(CaseProposal).order_by(CaseProposal.position))).scalars().all()
    )
    assert [p.input for p in proposals] == ["Can I return shoes?", "Can I return a hat?"]


async def test_readable_cases_that_break_a_rule_are_counted_apart(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.AGENT], 2)
    run = await _run_row(db, owner, agent)
    invented = {"origin": "knowledge", "input": "Invented?", "passage": "P99"}
    _model_answers(monkeypatch, agent, run, [_READABLE, _MALFORMED, invented])

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    await db.refresh(row)
    assert (row.status, row.proposed_count, row.unreadable_count, row.rejected_count) == (
        "ready",
        1,
        1,
        1,
    )


async def test_an_answer_with_no_readable_case_fails_as_unreadable(db, monkeypatch) -> None:
    """Not `ready` with nothing proposed: the generation fails as it always did."""
    owner, _, agent, dataset, _ = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.AGENT], 2)
    run = await _run_row(db, owner, agent)
    _model_answers(monkeypatch, agent, run, [_MALFORMED, _MALFORMED])

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    await db.refresh(row)
    await db.refresh(run)
    assert (row.status, row.run_id, row.proposed_count, row.unreadable_count) == (
        "failed",
        run.id,
        0,
        0,
    )
    assert row.error == (
        f"'{agent.name}' answered in a form that could not be read. Its run is in Activity."
    )
    assert run.error is not None and "none of the 2 cases" in run.error
    assert await db.scalar(select(func.count(CaseProposal.id))) == 0


@pytest.mark.parametrize("column", ["unreadable_count", "rejected_count"])
async def test_a_generation_cannot_leave_out_fewer_than_no_cases(db, column) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    db.add(
        CaseGeneration(
            organization_id=owner.organization_id,
            dataset_id=dataset.id,
            agent_id=agent.id,
            sources=["agent"],
            requested_count=1,
            **{column: -1},
        )
    )

    with pytest.raises(IntegrityError, match="ck_case_generation_counts"):
        await db.flush()


async def test_a_source_deleted_while_the_generator_ran_fails_the_generation(
    db, monkeypatch
) -> None:
    owner, _, agent, dataset, documents = await _setup(db)
    row, material, quotas = await _generation(db, owner, dataset, agent, [CaseOrigin.KNOWLEDGE], 1)
    run = await _run_row(db, owner, agent)
    run_id = run.id
    cited = next(p for p in material.passages if p.document_id == documents[0].id)
    await db.delete(documents[0])
    await db.commit()
    _answer(
        monkeypatch,
        DraftedCases(cases=[DraftedCase(origin="knowledge", input="Q?", passage=cited.ref)]),
        run=run,
    )

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    await db.refresh(row)
    assert (row.status, row.error, row.run_id) == ("failed", FAILED, run_id)
    assert await db.scalar(select(func.count(CaseProposal.id))) == 0


@pytest.mark.security
async def test_a_question_whose_asker_was_erased_meanwhile_drafts_nothing(db, monkeypatch) -> None:
    """The chat, the message and the run outlive an erased account with no link back
    to it, so a draft written after the purge would be found by no later one."""
    owner, org, agent, dataset, _ = await _setup(db)
    project = await project_repo.create(
        db,
        organization_id=org.id,
        owner_user_id=owner.user_id,
        name="Support",
        description="",
        instructions="",
        default_agent_id=None,
        backend="state",
        visibility="org",
    )
    erased, kept = await world.user(db), await world.user(db)
    for person, minutes in ((erased, 1), (kept, 2)):
        run, chat, _ = await world.asked(
            db, org, agent, kept, f"{person.email}?", minutes=minutes, author=person
        )
        chat.project_id, run.user_id = project.id, person.id
    await db.flush()
    row, material, quotas = await _generation(
        db, owner, dataset, agent, [CaseOrigin.CONVERSATION], 2
    )
    erased_id = erased.id
    await db.execute(delete(User).where(User.id == erased_id))
    await db.commit()
    _answer(
        monkeypatch,
        DraftedCases(
            cases=[
                DraftedCase(
                    origin="conversation",
                    input=f"A variant of {question.ref}",
                    reference_answer="An answer.",
                    question=question.ref,
                )
                for question in material.questions
            ]
        ),
        run=await _run_row(db, owner, agent),
    )

    await generate(
        db, generation_id=row.id, ctx=owner, prompt="p", material=material, quotas=quotas
    )

    asked_by = {question.ref: question.askers for question in material.questions}
    proposals = (await db.execute(select(CaseProposal))).scalars().all()
    assert [asked_by[p.input.removeprefix("A variant of ")] for p in proposals] == [(kept.id,)]
    assert sorted(asked_by.values()) == sorted([(erased_id,), (kept.id,)])


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


def _sessions(db):
    @asynccontextmanager
    async def session():
        yield db

    return session


def _worker(db, row: CaseGeneration) -> CaseGenerationWorker:
    return CaseGenerationWorker(
        row.id,
        row.organization_id,
        sessions=_sessions(db),
        vector_store=_Chunks(),  # ty: ignore[invalid-argument-type]
    )


async def _queued(db, owner, agent, dataset, *, count: int = 1, auto_accept: bool = False):
    row = CaseGeneration(
        organization_id=owner.organization_id,
        dataset_id=dataset.id,
        agent_id=agent.id,
        requested_by_user_id=owner.user_id,
        sources=["agent"],
        requested_count=count,
        auto_accept=auto_accept,
    )
    db.add(row)
    await db.commit()
    return row


async def test_a_queued_generation_runs_as_its_requester_and_says_so(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row = await _queued(db, owner, agent, dataset)
    calls = _answer(
        monkeypatch,
        DraftedCases(cases=[DraftedCase(origin="agent", input="Q?", reference_answer="A.")]),
        run=await _run_row(db, owner, agent),
    )
    published: list[ChangeEvent] = []

    async def publish(event: ChangeEvent) -> None:
        published.append(event)

    monkeypatch.setattr(change_feed, "publish", publish)

    await _worker(db, row).run()

    await db.refresh(row)
    assert (row.status, row.proposed_count) == ("ready", 1)
    assert calls.await_args is not None
    assert calls.await_args.args[0].user_id == owner.user_id
    [event] = published
    assert (event.resource, event.id, event.action, event.surface) == (
        "dataset",
        dataset.id,
        "updated",
        "run",
    )
    assert event.actor_user_id == owner.user_id
    # A second delivery of the job finds it ended and does nothing.
    await _worker(db, row).run()
    assert calls.await_count == 1
    await CaseGenerationWorker(uuid.uuid4(), owner.organization_id, sessions=_sessions(db)).run()


async def test_a_queued_generation_fails_when_its_requester_or_agent_is_gone(
    db, monkeypatch
) -> None:
    owner, org, agent, dataset, _ = await _setup(db)
    calls = _answer(monkeypatch, RuntimeError("no model may be called"))
    monkeypatch.setattr(change_feed, "publish", AsyncMock())
    left = await _queued(db, owner, agent, dataset)
    left.requested_by_user_id = None
    agentless = await _queued(db, owner, agent, dataset)
    agentless.agent_id = None
    refused = await _queued(db, owner, agent, dataset)
    await db.commit()
    org.ai_assistance_enabled = False
    await db.commit()

    for row in (left, agentless, refused):
        await _worker(db, row).run()
        await db.refresh(row)

    assert [(row.status, row.error) for row in (left, agentless)] == [
        ("failed", worker.REQUESTER_GONE),
        ("failed", worker.AGENT_GONE),
    ]
    assert refused.status == "failed"
    assert refused.error is not None and "AI assistance is switched off" in refused.error
    calls.assert_not_awaited()


async def test_a_requester_who_left_the_organization_is_no_one_to_run_as(db) -> None:
    owner, org, agent, dataset, _ = await _setup(db)
    row = await _queued(db, owner, agent, dataset)
    stranger = await world.user(db)
    row.requested_by_user_id = stranger.id

    assert await worker.requester(db, row) is None


async def test_an_auto_accepted_generation_becomes_a_version_on_its_own(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row = await _queued(db, owner, agent, dataset, count=2, auto_accept=True)
    _answer(
        monkeypatch,
        DraftedCases(
            cases=[
                DraftedCase(origin="agent", input="One?", reference_answer="A."),
                DraftedCase(origin="agent", input="Two?", reference_answer="B."),
            ]
        ),
        run=await _run_row(db, owner, agent),
    )
    monkeypatch.setattr(change_feed, "publish", AsyncMock())

    await _worker(db, row).run()

    await db.refresh(row)
    assert (row.status, row.proposed_count, row.accepted_count) == ("ready", 2, 2)
    held = await DatasetService(db).list_cases(owner, dataset.id)
    assert [(case.input, case.source) for case in held.items] == [
        ("One?", "synthetic"),
        ("Two?", "synthetic"),
    ]
    assert await db.scalar(select(func.count(CaseProposal.id))) == 0
    audit = (
        await db.execute(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.action == "dataset.proposals_auto_accepted"
            )
        )
    ).scalar_one()
    assert audit == {
        "name": dataset.name,
        "generation_id": str(row.id),
        "accepted": 2,
        "version": 1,
    }


async def test_an_auto_accept_the_dataset_refuses_leaves_the_drafts_waiting(
    db, monkeypatch
) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row = await _queued(db, owner, agent, dataset, auto_accept=True)
    _answer(
        monkeypatch,
        DraftedCases(cases=[DraftedCase(origin="agent", input="One?", reference_answer="A.")]),
        run=await _run_row(db, owner, agent),
    )
    monkeypatch.setattr(change_feed, "publish", AsyncMock())
    monkeypatch.setattr(
        DatasetService,
        "add_generated",
        AsyncMock(side_effect=BadRequestError(message="This dataset is full")),
    )

    await _worker(db, row).run()

    await db.refresh(row)
    assert (row.status, row.accepted_count) == ("ready", 0)
    assert await db.scalar(select(func.count(CaseProposal.id))) == 1


async def test_a_failed_or_already_decided_generation_accepts_nothing(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    row = await _queued(db, owner, agent, dataset, auto_accept=True)
    _answer(monkeypatch, RuntimeError("socket closed"))
    monkeypatch.setattr(change_feed, "publish", AsyncMock())

    await _worker(db, row).run()

    await db.refresh(row)
    assert (row.status, row.error) == ("failed", FAILED)
    service = _service(db)
    assert await service.accept_drafted(owner, row) is None
    assert (await DatasetService(db).read(owner, dataset.id)).latest_version == 0


async def test_a_generation_whose_job_died_is_failed_by_its_settler(db, monkeypatch) -> None:
    owner, _, agent, dataset, _ = await _setup(db)
    running = await _queued(db, owner, agent, dataset)
    ended = await _queued(db, owner, agent, dataset)
    ended.status = "ready"
    await db.commit()
    monkeypatch.setattr(worker, "get_worker_db_context", _sessions(db))

    for row in (running, ended):
        await settle_ended(
            "generate-cases",
            {"generation_id": str(row.id), "organization_id": str(owner.organization_id)},
            "the worker was killed",
        )
        await db.refresh(row)

    assert [(row.status, row.error) for row in (running, ended)] == [
        ("failed", worker.STOPPED),
        ("ready", None),
    ]


async def test_the_job_hands_its_generation_to_the_worker(monkeypatch) -> None:
    ran: list[tuple[uuid.UUID, uuid.UUID]] = []

    class Worker:
        def __init__(self, generation_id, organization_id) -> None:
            ran.append((generation_id, organization_id))

        async def run(self) -> None:
            return None

    monkeypatch.setattr(worker, "CaseGenerationWorker", Worker)
    job = GenerateCases(generation_id=uuid.uuid4(), organization_id=uuid.uuid4())

    await case_generation_tasks.generate_cases(job)

    assert ran == [(job.generation_id, job.organization_id)]


async def test_a_worker_reads_knowledge_through_the_process_s_vector_store(monkeypatch) -> None:
    store = _Chunks()
    made: list[object] = []

    def process_vector_store(rag, embedder) -> _Chunks:
        made.append((rag, embedder))
        return store

    monkeypatch.setattr(worker, "process_vector_store", process_vector_store)
    monkeypatch.setattr(worker, "EmbeddingService", lambda rag: "embedder")
    job = CaseGenerationWorker(uuid.uuid4(), uuid.uuid4())

    assert job._store() is store
    assert job._store() is store
    assert len(made) == 1
