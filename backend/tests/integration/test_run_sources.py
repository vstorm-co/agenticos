"""Activity's Source filter and what each platform agent's run says it worked on.

A platform agent's run is recorded on the `eval` surface, so leaving evaluation
out of the default list also left out every run a knowledge-gap draft or an
Improve session links to. These read Postgres because the filter is a subquery on
the agent's kind, and each origin is a lookup across another domain's table.
"""

import uuid
from decimal import Decimal

import pytest

from app.db.models.agent import Agent, AgentKind
from app.db.models.agent_run import RunSource, RunSurface
from app.db.models.authoring import AuthoringRequest
from app.db.models.case_generation import CaseGeneration
from app.db.models.conversation import Message
from app.db.models.dataset import Dataset
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import KnowledgeGapClassification, KnowledgeGapTopic
from app.db.models.organization import Organization
from app.repositories import improvement_repo
from app.repositories.agent_run import RunFilters
from app.services.agent_runner import AgentRunnerService
from tests.integration.test_run_history_filters import (
    _agent,
    _conversation,
    _ctx,
    _listed,
    _org,
    _run,
)

pytestmark = pytest.mark.anyio


async def _platform(db, org: Organization, kind: AgentKind, name: str) -> Agent:
    agent = await _agent(db, org)
    agent.kind = kind.value
    agent.name = name
    await db.flush()
    return agent


async def _knowledge_base(db, org: Organization) -> KnowledgeBase:
    kb = KnowledgeBase(
        organization_id=org.id,
        name="handbook",
        collection_name=f"handbook_{uuid.uuid4().hex[:8]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
    )
    db.add(kb)
    await db.flush()
    return kb


async def test_the_source_filter_splits_conversations_evals_and_platform_work(db) -> None:
    org, owner = await _org(db)
    clerk = await _agent(db, org)
    judge = await _platform(db, org, AgentKind.JUDGE, "Judge")
    chat = await _run(db, org, clerk)
    answer = await _run(db, org, clerk, surface=RunSurface.EVAL.value)
    grading = await _run(db, org, judge, surface=RunSurface.EVAL.value)

    everything, total = await _listed(db, org, owner)
    assert set(everything) == {str(chat.id), str(answer.id), str(grading.id)} and total == 3
    for source, expected in [
        (RunSource.CONVERSATION, chat),
        (RunSource.EVALUATION, answer),
        (RunSource.SYSTEM, grading),
    ]:
        assert await _listed(db, org, owner, filters=RunFilters(source=source)) == (
            [str(expected.id)],
            1,
        )


async def test_each_platform_run_names_its_agent_and_where_its_work_is(db) -> None:
    org, owner = await _org(db)
    clerk = await _agent(db, org)
    kb = await _knowledge_base(db, org)
    dataset = Dataset(id=uuid.uuid4(), organization_id=org.id, name="Refunds")
    db.add(dataset)
    await db.flush()
    session = await improvement_repo.create_run(
        db,
        organization_id=org.id,
        agent_id=clerk.id,
        created_by_user_id=owner.id,
        created_by_api_key_id=None,
        base_version_id=None,
        base_draft_hash="a" * 64,
        dataset_id=dataset.id,
        dataset_version=1,
        suite_id=None,
        suite_hash=None,
        scoring_hash="s" * 64,
        window_days=30,
        estimate_usd=Decimal("0.04"),
        budget_usd=Decimal("0.04"),
        max_iterations=3,
    )
    improver = await _platform(db, org, AgentKind.IMPROVER, "Improver")
    drafter = await _platform(db, org, AgentKind.DRAFTER, "Knowledge drafter")
    classifier = await _platform(db, org, AgentKind.CLASSIFIER, "Gap reader")
    generator = await _platform(db, org, AgentKind.GENERATOR, "Case writer")
    judge = await _platform(db, org, AgentKind.JUDGE, "Judge")
    eval_surface = {"surface": RunSurface.EVAL.value}
    improving = await _run(db, org, improver, **eval_surface)
    drafting = await _run(db, org, drafter, **eval_surface)
    reading = await _run(db, org, classifier, **eval_surface)
    writing = await _run(db, org, generator, **eval_surface)
    grading = await _run(db, org, judge, **eval_surface)
    answering = await _run(db, org, clerk, **eval_surface)
    request = AuthoringRequest(
        organization_id=org.id,
        kind="improve",
        target="agent",
        agent_id=clerk.id,
        status="completed",
        estimate_usd=Decimal("0.01"),
        window_days=30,
        run_ids=[improving.id],
        improvement_run_id=session.id,
    )
    topic = KnowledgeGapTopic(
        organization_id=org.id,
        knowledge_base_id=kb.id,
        centroid=[0.1],
        embedding_model="m",
        draft_run_id=drafting.id,
    )
    answered = await _run(db, org, clerk)
    conversation = await _conversation(db, org)
    message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        run_id=answered.id,
        role="assistant",
        content="Parking is on level 2",
    )
    generation = CaseGeneration(
        organization_id=org.id,
        dataset_id=dataset.id,
        sources=["conversations"],
        requested_count=1,
        run_id=writing.id,
    )
    db.add_all([request, topic, message, generation])
    await db.flush()
    db.add(
        KnowledgeGapClassification(
            message_id=message.id,
            knowledge_base_id=kb.id,
            organization_id=org.id,
            signal="none",
            run_id=reading.id,
        )
    )
    await db.flush()

    origins = await AgentRunnerService(db).origins(
        _ctx(org, owner),
        [improving.id, drafting.id, reading.id, writing.id, grading.id, answering.id],
    )

    assert answering.id not in origins
    assert origins[improving.id].model_dump(exclude_none=True) == {
        "kind": "improve",
        "agent_name": "Improver",
        "agent_id": clerk.id,
        "improvement_id": session.id,
    }
    assert origins[drafting.id].model_dump(exclude_none=True) == {
        "kind": "knowledge_gaps",
        "agent_name": "Knowledge drafter",
        "topic_id": topic.id,
        "knowledge_base_id": kb.id,
    }
    assert origins[reading.id].model_dump(exclude_none=True) == {
        "kind": "knowledge_gaps",
        "agent_name": "Gap reader",
        "knowledge_base_id": kb.id,
    }
    assert origins[writing.id].model_dump(exclude_none=True) == {
        "kind": "test_questions",
        "agent_name": "Case writer",
        "dataset_id": dataset.id,
    }
    assert origins[grading.id].model_dump(exclude_none=True) == {
        "kind": "grader",
        "agent_name": "Judge",
    }


async def test_another_organization_sees_neither_the_runs_nor_their_origins(db) -> None:
    org, owner = await _org(db)
    other, stranger = await _org(db)
    judge = await _platform(db, org, AgentKind.JUDGE, "Judge")
    grading = await _run(db, org, judge, surface=RunSurface.EVAL.value)

    assert await _listed(db, other, stranger, filters=RunFilters(source=RunSource.SYSTEM)) == (
        [],
        0,
    )
    assert await AgentRunnerService(db).origins(_ctx(other, stranger), [grading.id]) == {}
    assert await AgentRunnerService(db).origins(_ctx(org, owner), []) == {}
