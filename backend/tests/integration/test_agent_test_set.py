"""Building an agent's test set from its rated answers, against Postgres.

The model is never called: the generator's answer is stood in for at
`SystemAgentRunner.run`, and its readiness at `require_runnable`.

The claims:

- an agent with rated answers and no test set gets one: a thumbs-up kept as the
  good answer, a thumbs-down as the answer to avoid with its comment as the note,
  each question on its own, and more questions written for it that join the test
  set once ready;
- grading compares with the good answer and avoids the bad one, on a judge of
  another model than the agent's - or on the default judge, said in words, where
  there is no other model;
- an agent with a test set gets a new version, keeping the cases it held;
- only questions from outside the evidence conversations count as able to
  measure a change, and too few of them are said to be too few;
- eval and isolated runs are not evidence of anything a person rated, a caller
  whose role may not edit datasets is refused, and an agent they may not see is
  not found.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.background_job import BackgroundJob
from app.db.models.case_generation import CaseGeneration
from app.db.models.conversation import Message
from app.db.models.credential import ModelProfile
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import agent_repo
from app.schemas.scoring import DatasetScoring
from app.services import agent_test_set, change_feed
from app.services.agent_test_set import REASONS, AgentTestSetService
from app.services.case_generation.drafts import DraftedCase, DraftedCases
from app.services.case_generation.worker import CaseGenerationWorker
from app.services.dataset import DatasetService
from app.services.rag.models import DocumentChunk
from app.services.system_agent_runner import SystemAgentResult, SystemAgentRunner
from tests.integration import case_generation_world as world

pytestmark = pytest.mark.anyio


class _Chunks:
    async def get_document_chunks(
        self, collection_name: str, document_id: str, tenant: uuid.UUID | None = None
    ) -> list[DocumentChunk]:
        del collection_name, document_id, tenant
        return []


def _service(db) -> AgentTestSetService:
    return AgentTestSetService(db, vector_store=_Chunks())  # ty: ignore[invalid-argument-type]


async def _profile(db, org: Organization, model: str, provider: str) -> ModelProfile:
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=org.id,
        label=f"{model}-{uuid.uuid4().hex[:4]}",
        provider=provider,
        model=model,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _world(db, *, models: int = 2):
    """An owner, a colleague, and an agent on the first of `models` models."""
    person = await world.user(db)
    org = await world.org(db, person)
    owner = await world.member(db, org, OrgRoleName.OWNER, person)
    colleague = await world.member(db, org, OrgRoleName.MEMBER)
    models_set_up = [("claude-sonnet-4-5", "anthropic"), ("gpt-4.1-nano", "openai")][:models]
    profiles = [await _profile(db, org, model, provider) for model, provider in models_set_up]
    agent = await world.agent(db, org, visibility="org")
    await world.publish(
        db,
        agent,
        {
            "name": "Clerk",
            "instructions": "Answer about returns.",
            "model_profile_id": str(profiles[0].id),
        },
    )
    return org, owner, colleague, agent, profiles


async def _rate(
    db, org, agent, ctx: AuthContext, question: str, *, rating: int, minutes: int, **kw
):
    person = await db.get(User, ctx.user_id)
    return await world.asked(db, org, agent, person, question, minutes=minutes, rating=rating, **kw)


def _generator(monkeypatch, *, ready: bool = True) -> None:
    monkeypatch.setattr(SystemAgentRunner, "require_runnable", AsyncMock())
    if not ready:
        monkeypatch.setattr(
            SystemAgentRunner,
            "require_runnable",
            AsyncMock(
                side_effect=SystemAgentUnavailableError(
                    "Not published", key="case_generator", reason="unpublished"
                )
            ),
        )


def _sessions(db):
    @asynccontextmanager
    async def session():
        yield db

    return session


async def test_an_agent_with_rated_answers_gets_a_test_set_graded_on_another_model(
    db, monkeypatch
) -> None:
    org, owner, colleague, agent, (answers_on, other) = await _world(db)
    _generator(monkeypatch)
    _, own_good, _ = await _rate(
        db, org, agent, owner, "How long do refunds take?", rating=1, minutes=1
    )
    _, bad, _ = await _rate(
        db, org, agent, owner, "Can I return a used kettle?", rating=-1, minutes=2, comment="Wrong"
    )
    _, theirs, _ = await _rate(
        db, org, agent, colleague, "Do you ship to Canada?", rating=1, minutes=3
    )
    await _rate(db, org, agent, owner, "A test?", rating=-1, minutes=4, surface="eval")

    built = await _service(db).bootstrap_for_agent(owner, agent.id)

    assert built.created
    assert built.counts.model_dump() == {
        "rated_good": 2,
        "rated_bad": 1,
        "skipped": 0,
        "from_others": 1,
        "generated_requested": 2,
    }
    dataset = await DatasetService(db).read(owner, built.dataset_id)
    assert (dataset.name, dataset.agent_id, dataset.latest_version) == (
        "Clerk - test questions",
        agent.id,
        1,
    )
    cases = {
        case.input: case for case in (await DatasetService(db).list_cases(owner, dataset.id)).items
    }
    assert set(cases) == {
        "How long do refunds take?",
        "Can I return a used kettle?",
        "Do you ship to Canada?",
    }
    kettle = cases["Can I return a used kettle?"]
    assert (kettle.counter_example, kettle.reference_answer, kettle.note, kettle.history) == (
        "An answer.",
        None,
        "Wrong",
        [],
    )
    assert cases["How long do refunds take?"].reference_answer == "An answer."
    scoring = DatasetScoring.model_validate(dataset.scoring)
    assert scoring.judge.enabled and scoring.reference.enabled and scoring.judge.criteria
    assert built.judge.independent and built.judge.agent_id == scoring.judge.agent_id
    judge = await agent_repo.get(db, scoring.judge.agent_id, organization_id=org.id)
    assert judge is not None and judge.name == "Clerk - grader"
    version = await agent_repo.get_version(db, judge.current_version_id, organization_id=org.id)
    assert version is not None and version.spec["model_profile_id"] == str(other.id)
    assert (built.gradable, built.too_few) == (3, False)
    job = (await db.execute(select(BackgroundJob))).scalar_one()
    assert job.payload["generation_id"] == str(built.generation_id)
    del own_good, theirs, answers_on

    # The generator's questions join the test set once written, and every one counts.
    await db.commit()
    row = await db.get(CaseGeneration, built.generation_id)
    assert row is not None and row.auto_accept
    calls = AsyncMock(
        return_value=SystemAgentResult(
            output=DraftedCases(
                cases=[
                    DraftedCase(origin="agent", input="Can I cancel?", reference_answer="Yes."),
                    DraftedCase(origin="agent", input="Is it free?", reference_answer="No."),
                ]
            ),
            run=await _run(db, owner, agent),
        )
    )
    monkeypatch.setattr(SystemAgentRunner, "run", calls)
    monkeypatch.setattr(change_feed, "publish", AsyncMock())
    await CaseGenerationWorker(
        row.id,
        org.id,
        sessions=_sessions(db),
        vector_store=_Chunks(),  # ty: ignore[invalid-argument-type]
    ).run()

    evidence = [cases[q].source_conversation_id for q in cases]
    service = _service(db)
    assert await service.gradable_count(owner, dataset.id) == 5
    assert (
        await service.gradable_count(
            owner, dataset.id, evidence_conversation_ids=[e for e in evidence if e]
        )
        == 2
    )


async def _run(db, ctx: AuthContext, agent: Agent) -> AgentRun:
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


async def _rated_at(db, conversation_id, at: datetime) -> None:
    rating = (
        await db.execute(
            select(MessageRating)
            .join(Message, Message.id == MessageRating.message_id)
            .where(Message.conversation_id == conversation_id)
        )
    ).scalar_one()
    rating.created_at = at
    await db.flush()


async def test_an_agent_with_a_test_set_gets_a_new_version_keeping_its_cases(
    db, monkeypatch
) -> None:
    org, owner, _, agent, _ = await _world(db)
    _generator(monkeypatch)
    _, old, _ = await _rate(db, org, agent, owner, "How long do refunds take?", rating=1, minutes=1)
    await _rated_at(db, old.id, datetime(2026, 1, 1, tzinfo=UTC))
    first = await _service(db).bootstrap_for_agent(owner, agent.id, more=1)
    _, new, _ = await _rate(db, org, agent, owner, "Do you gift wrap?", rating=-1, minutes=5)
    await _rated_at(db, new.id, datetime(2026, 3, 1, tzinfo=UTC))

    since = await _service(db).bootstrap_for_agent(
        owner, agent.id, since=datetime(2026, 2, 1, tzinfo=UTC), more=1
    )
    again = await _service(db).bootstrap_for_agent(owner, agent.id, more=1)

    assert (since.dataset_id, since.created, since.version) == (first.dataset_id, False, 2)
    assert (since.counts.rated_good, since.counts.rated_bad, since.counts.skipped) == (0, 1, 0)
    assert (again.version, again.counts.skipped) == (2, 2)
    held = await DatasetService(db).list_cases(owner, first.dataset_id)
    assert [case.input for case in held.items] == ["How long do refunds take?", "Do you gift wrap?"]


async def test_with_one_model_the_default_judge_grades_and_the_reason_is_given(
    db, monkeypatch
) -> None:
    org, owner, _, agent, _ = await _world(db, models=1)
    _generator(monkeypatch)
    await _rate(db, org, agent, owner, "How long do refunds take?", rating=1, minutes=1)

    built = await _service(db).bootstrap_for_agent(owner, agent.id)

    assert built.judge.model_dump() == {
        "agent_id": None,
        "independent": False,
        "reason": REASONS["one_model"],
        "reason_code": "one_model",
    }
    scoring = DatasetScoring.model_validate(
        (await DatasetService(db).read(owner, built.dataset_id)).scoring
    )
    assert scoring.judge.enabled and scoring.judge.agent_id is None and scoring.reference.enabled


async def test_an_existing_judge_on_another_model_is_kept(db, monkeypatch) -> None:
    org, owner, _, agent, _ = await _world(db)
    _generator(monkeypatch)
    first = await _service(db).bootstrap_for_agent(owner, agent.id, more=1)
    again = await _service(db).bootstrap_for_agent(owner, agent.id, more=1)

    assert again.judge.agent_id == first.judge.agent_id and again.judge.independent
    judges = (await db.execute(select(Agent).where(Agent.kind == "judge"))).scalars().all()
    assert len(judges) == 1


async def test_with_ai_assistance_off_nothing_is_graded_or_written_and_it_says_why(
    db, monkeypatch
) -> None:
    org, owner, _, agent, _ = await _world(db)
    _generator(monkeypatch)
    await _rate(db, org, agent, owner, "How long do refunds take?", rating=1, minutes=1)
    org.ai_assistance_enabled = False
    await db.flush()

    built = await _service(db).bootstrap_for_agent(owner, agent.id)

    assert (built.judge.reason_code, built.generation_skipped) == ("ai_off", "ai_off")
    assert built.judge.reason == REASONS["ai_off"]
    assert (built.gradable, built.too_few) == (0, True)
    estimate = await _service(db).estimate_bootstrap(owner, agent.id)
    assert estimate.model_dump() == {"cost_usd": Decimal(0), "priced": True, "generate": 0}


async def test_too_few_questions_are_said_to_be_too_few(db, monkeypatch) -> None:
    org, owner, _, agent, _ = await _world(db)
    _generator(monkeypatch, ready=False)
    await _rate(db, org, agent, owner, "How long do refunds take?", rating=1, minutes=1)

    built = await _service(db).bootstrap_for_agent(owner, agent.id)

    assert (built.gradable, built.too_few, built.generation_skipped) == (1, True, "unavailable")
    assert built.generation_id is None
    assert (await db.execute(select(BackgroundJob))).first() is None


async def test_enough_questions_ask_for_none_unless_more_are_asked_for(db, monkeypatch) -> None:
    org, owner, _, agent, _ = await _world(db)
    _generator(monkeypatch)
    for minute, question in enumerate(["One?", "Two?", "Three?", "Four?", "Five?"]):
        await _rate(db, org, agent, owner, question, rating=1, minutes=minute)

    built = await _service(db).bootstrap_for_agent(owner, agent.id)
    more = await _service(db).bootstrap_for_agent(owner, agent.id, more=5)

    assert (built.gradable, built.generation_skipped, built.counts.generated_requested) == (
        5,
        "enough",
        0,
    )
    assert (more.counts.generated_requested, more.generation_skipped) == (5, None)


async def test_a_question_the_caller_cannot_open_is_left_out(db, monkeypatch) -> None:
    org, owner, colleague, agent, _ = await _world(db)
    _generator(monkeypatch)
    await _rate(db, org, agent, owner, "The owner's question?", rating=-1, minutes=1)
    await _rate(db, org, agent, colleague, "Their own question?", rating=1, minutes=2)

    built = await _service(db).bootstrap_for_agent(colleague, agent.id)

    assert (built.counts.rated_good, built.counts.rated_bad, built.counts.skipped) == (1, 0, 1)
    assert built.counts.from_others == 0


@pytest.mark.security
async def test_a_caller_who_may_not_edit_datasets_or_see_the_agent_is_refused(
    db, monkeypatch
) -> None:
    org, owner, _, agent, _ = await _world(db)
    _generator(monkeypatch)
    viewer = await world.member(db, org, OrgRoleName.VIEWER)
    stranger_org = await world.org(db, await world.user(db))
    stranger = await world.member(db, stranger_org, OrgRoleName.OWNER)
    service = _service(db)

    for attempt in (service.bootstrap_for_agent, service.estimate_bootstrap):
        with pytest.raises(AuthorizationError):
            await attempt(viewer, agent.id)
        with pytest.raises(NotFoundError):
            await attempt(stranger, agent.id)
    assert (await db.execute(select(CaseGeneration))).first() is None
    del owner


async def test_the_estimate_prices_the_questions_to_write(db, monkeypatch) -> None:
    org, owner, _, agent, _ = await _world(db)
    _generator(monkeypatch)

    estimate = await _service(db).estimate_bootstrap(owner, agent.id, more=10)

    assert (estimate.priced, estimate.generate) == (True, 10)
    assert estimate.cost_usd > 0
    del org


async def test_a_generator_model_with_no_price_is_said_to_be_unpriced(db, monkeypatch) -> None:
    org, owner, _, agent, profiles = await _world(db)
    _generator(monkeypatch)
    for profile in profiles:
        profile.model = "no-such-model-anywhere"
    await db.flush()

    estimate = await _service(db).estimate_bootstrap(owner, agent.id)

    assert estimate.model_dump() == {"cost_usd": Decimal(0), "priced": False, "generate": 5}
    del org


async def test_a_test_set_the_caller_may_not_edit_is_left_for_one_of_their_own(
    db, monkeypatch
) -> None:
    org, owner, colleague, agent, _ = await _world(db)
    _generator(monkeypatch)
    owners = await _service(db).bootstrap_for_agent(owner, agent.id, more=1)

    theirs = await _service(db).bootstrap_for_agent(colleague, agent.id, more=1)

    assert theirs.created and theirs.dataset_id != owners.dataset_id
    named = await DatasetService(db).read(colleague, theirs.dataset_id)
    assert named.name == "Clerk - test questions (2)"
    monkeypatch.setattr(agent_test_set, "_NAME_TRIES", 1)
    stranger = await world.member(db, org, OrgRoleName.MEMBER)
    with pytest.raises(BadRequestError, match="Every name for this agent's test set is taken"):
        await _service(db).bootstrap_for_agent(stranger, agent.id)


async def test_a_judge_on_the_agent_s_own_model_is_replaced_by_one_on_another(
    db, monkeypatch
) -> None:
    org, owner, _, agent, (claude, gpt) = await _world(db)
    _generator(monkeypatch)
    first = await _service(db).bootstrap_for_agent(owner, agent.id, more=1)

    async def answer_on(profile: ModelProfile) -> None:
        version = await agent_repo.get_version(db, agent.current_version_id, organization_id=org.id)
        assert version is not None
        version.spec = {**version.spec, "model_profile_id": str(profile.id)}
        await db.flush()

    await answer_on(gpt)
    again = await _service(db).bootstrap_for_agent(owner, agent.id, more=1)

    assert again.judge.independent and again.judge.agent_id != first.judge.agent_id
    judge = await agent_repo.get(db, again.judge.agent_id, organization_id=org.id)
    assert judge is not None and judge.name == "Clerk - grader (2)"

    await answer_on(claude)
    monkeypatch.setattr(agent_test_set, "_NAME_TRIES", 1)
    with pytest.raises(BadRequestError, match="Every name for this agent's grader is taken"):
        await _service(db).bootstrap_for_agent(owner, agent.id, more=1)


async def test_an_agent_with_knowledge_asks_for_questions_from_it_too(db, monkeypatch) -> None:
    org, owner, _, _, (answers_on, _) = await _world(db)
    _generator(monkeypatch)
    collection = await world.collection(db, org)
    agent = await world.agent(db, org, visibility="org")
    await world.publish(
        db,
        agent,
        {
            "name": "Librarian",
            "instructions": "Answer from the handbook.",
            "model_profile_id": str(answers_on.id),
            "collection_ids": [str(collection.id)],
            "capabilities": [{"id": "knowledge"}],
        },
    )

    built = await _service(db).bootstrap_for_agent(owner, agent.id)

    # Its knowledge base holds no document to draft from, so nothing is asked for.
    assert (built.generation_skipped, built.counts.generated_requested) == ("nothing_to_draft", 0)


async def test_an_unfinished_draft_agent_is_graded_and_priced_as_far_as_it_can_be(
    db, monkeypatch
) -> None:
    org, owner, _, _, _ = await _world(db)
    _generator(monkeypatch)
    draft = await world.agent(db, org, visibility="org")

    built = await _service(db).bootstrap_for_agent(owner, draft.id)
    estimate = await _service(db).estimate_bootstrap(owner, draft.id)

    assert built.judge.independent and built.generation_skipped == "nothing_to_draft"
    assert (built.gradable, built.too_few) == (0, True)
    assert estimate.generate == 0
