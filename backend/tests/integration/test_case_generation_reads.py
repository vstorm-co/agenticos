"""What the case generator may read, and the queue its drafts wait in, against Postgres.

The claims a mocked session cannot make:

- the questions put to an agent come back rated-down first, from that agent and
  that organization only, with the comment left on the disappointing answer;
- an agent's collections and their finished documents are read through the
  organization, so a collection id from another tenant reads as absent;
- two reviewers deciding the same proposal at once get it once between them;
- deleting a conversation, or erasing a person, takes the proposals drafted
  from them along.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.case_generation import CaseGeneration, CaseOrigin, CaseProposal
from app.db.models.conversation import Conversation, Message
from app.db.models.dataset import Dataset
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.user import User
from app.repositories import (
    agent_run_repo,
    case_generation_repo,
    knowledge_base_repo,
    personal_data_repo,
    rag_document_repo,
)

pytestmark = pytest.mark.anyio

_START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


async def _user(db) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def _org(db, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    return org


async def _agent(db, org: Organization) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _asked(
    db,
    org: Organization,
    agent: Agent,
    person: User,
    question: str,
    *,
    minutes: int,
    rating: int | None = None,
    comment: str | None = None,
) -> tuple[AgentRun, Conversation, Message]:
    """A conversation in which `person` asked `agent` one question and got an answer."""
    conversation = Conversation(
        id=uuid.uuid4(), user_id=person.id, organization_id=org.id, title="Support"
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        user_id=person.id,
        conversation_id=conversation.id,
        status="completed",
        started_at=_START + timedelta(minutes=minutes),
    )
    db.add(run)
    await db.flush()
    asked = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        run_id=run.id,
        role="user",
        content=question,
        created_at=_START + timedelta(minutes=minutes),
    )
    answer = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        run_id=run.id,
        agent_id=agent.id,
        role="assistant",
        content="An answer.",
        created_at=_START + timedelta(minutes=minutes, seconds=5),
    )
    db.add_all([asked, answer])
    await db.flush()
    if rating is not None:
        db.add(
            MessageRating(message_id=answer.id, user_id=person.id, rating=rating, comment=comment)
        )
        await db.flush()
    return run, conversation, asked


async def _collection(db, org: Organization | None) -> KnowledgeBase:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name=f"Docs {uuid.uuid4().hex[:6]}",
        scope=KBScope.ORG.value if org else KBScope.PERSONAL.value,
        organization_id=org.id if org else None,
        collection_name=f"c_{uuid.uuid4().hex[:12]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        visibility="org",
    )
    db.add(kb)
    await db.flush()
    return kb


async def _document(db, kb: KnowledgeBase, status: DocumentStatus, name: str) -> RAGDocument:
    document = RAGDocument(
        id=uuid.uuid4(),
        collection_name=kb.collection_name,
        filename=name,
        filesize=4,
        filetype="md",
        storage_path="",
        status=status,
        chunk_count=3,
        ingestion_config={},
        knowledge_base_id=kb.id,
    )
    db.add(document)
    await db.flush()
    return document


async def _dataset(db, org: Organization) -> Dataset:
    dataset = Dataset(id=uuid.uuid4(), organization_id=org.id, name=f"d-{uuid.uuid4().hex[:6]}")
    db.add(dataset)
    await db.flush()
    return dataset


async def _proposals(
    db, org: Organization, dataset: Dataset, agent: Agent, count: int, **source: uuid.UUID
) -> tuple[CaseGeneration, list[CaseProposal]]:
    generation = await case_generation_repo.create_generation(
        db,
        organization_id=org.id,
        dataset_id=dataset.id,
        agent_id=agent.id,
        requested_by_user_id=None,
        sources=["conversation"],
        requested_count=count,
    )
    proposals = [
        CaseProposal(
            id=uuid.uuid4(),
            organization_id=org.id,
            generation_id=generation.id,
            dataset_id=dataset.id,
            position=index,
            origin=CaseOrigin.CONVERSATION.value,
            input=f"question {index}",
            **source,
        )
        for index in range(count)
    ]
    await case_generation_repo.add_proposals(db, proposals)
    return generation, proposals


async def test_questions_come_back_rated_down_first_from_this_agent_only(db) -> None:
    person = await _user(db)
    org = await _org(db, person)
    agent = await _agent(db, org)
    other_agent = await _agent(db, org)
    await _asked(db, org, agent, person, "Oldest", minutes=1)
    await _asked(db, org, agent, person, "Newest", minutes=30)
    await _asked(db, org, agent, person, "Disliked", minutes=10, rating=-1, comment="Wrong window")
    await _asked(db, org, agent, person, "Liked", minutes=20, rating=1, comment="Great")
    await _asked(db, org, other_agent, person, "Someone else's", minutes=40, rating=-1)

    questions = await agent_run_repo.questions_asked(
        db, organization_id=org.id, agent_id=agent.id, limit=10
    )

    assert [q.content for q in questions] == ["Disliked", "Newest", "Liked", "Oldest"]
    assert questions[0].rated_down is True
    assert questions[0].comment == "Wrong window"
    assert questions[2].rated_down is False
    assert questions[2].comment is None


async def test_questions_never_cross_into_another_organization(db) -> None:
    person = await _user(db)
    mine = await _org(db, person)
    theirs = await _org(db, person)
    their_agent = await _agent(db, theirs)
    await _asked(db, theirs, their_agent, person, "Their secret question", minutes=1)

    assert (
        await agent_run_repo.questions_asked(
            db, organization_id=mine.id, agent_id=their_agent.id, limit=10
        )
        == []
    )
    found = await agent_run_repo.questions_asked(
        db, organization_id=theirs.id, agent_id=their_agent.id, limit=10
    )
    assert [q.content for q in found] == ["Their secret question"]


async def test_questions_are_capped(db) -> None:
    person = await _user(db)
    org = await _org(db, person)
    agent = await _agent(db, org)
    for minute in range(5):
        await _asked(db, org, agent, person, f"q{minute}", minutes=minute)

    questions = await agent_run_repo.questions_asked(
        db, organization_id=org.id, agent_id=agent.id, limit=2
    )

    assert [q.content for q in questions] == ["q4", "q3"]


async def test_collections_and_documents_are_read_through_the_organization(db) -> None:
    person = await _user(db)
    org = await _org(db, person)
    other = await _org(db, person)
    first = await _collection(db, org)
    second = await _collection(db, org)
    foreign = await _collection(db, other)
    personal = await _collection(db, None)
    done = await _document(db, first, DocumentStatus.DONE, "handbook.md")
    await _document(db, first, DocumentStatus.ERROR, "broken.md")
    await _document(db, first, DocumentStatus.PROCESSING, "parsing.md")
    later = await _document(db, second, DocumentStatus.DONE, "faq.md")
    await _document(db, foreign, DocumentStatus.DONE, "theirs.md")

    collections = await knowledge_base_repo.get_in_organization(
        db, [second.id, foreign.id, personal.id, first.id], organization_id=org.id
    )
    documents = await rag_document_repo.indexed_in(
        db, [first.id, second.id, foreign.id], organization_id=org.id, limit=10
    )

    assert [kb.id for kb in collections] == [second.id, first.id]
    assert {doc.id for doc in documents} == {done.id, later.id}
    assert await knowledge_base_repo.get_in_organization(db, [], organization_id=org.id) == []
    assert await rag_document_repo.indexed_in(db, [], organization_id=org.id, limit=10) == []


async def test_a_proposal_is_taken_once_however_many_reviewers_decide_it(db, engine) -> None:
    person = await _user(db)
    org = await _org(db, person)
    agent = await _agent(db, org)
    dataset = await _dataset(db, org)
    _, proposals = await _proposals(db, org, dataset, agent, 2)
    await db.commit()
    ids = [proposals[1].id, proposals[0].id]

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def take() -> list[CaseProposal]:
        async with session_factory() as session:
            taken = await case_generation_repo.take_proposals(
                session, dataset.id, ids, organization_id=org.id
            )
            await session.commit()
            return taken

    first, second = await asyncio.gather(take(), take())

    assert sorted(len(batch) for batch in (first, second)) == [0, 2]
    winner = first or second
    assert [p.id for p in winner] == ids
    assert [p.input for p in winner] == ["question 1", "question 0"]


async def test_taking_and_counting_stay_inside_the_dataset_and_tenant(db) -> None:
    person = await _user(db)
    org = await _org(db, person)
    other = await _org(db, person)
    agent = await _agent(db, org)
    dataset = await _dataset(db, org)
    empty = await _dataset(db, org)
    generation, proposals = await _proposals(db, org, dataset, agent, 3)

    assert (
        await case_generation_repo.take_proposals(
            db, dataset.id, [proposals[0].id], organization_id=other.id
        )
        == []
    )
    assert (
        await case_generation_repo.take_proposals(
            db, empty.id, [proposals[0].id], organization_id=org.id
        )
        == []
    )
    assert (
        await case_generation_repo.take_proposals(db, dataset.id, [], organization_id=org.id) == []
    )
    assert await case_generation_repo.count_pending(
        db, [dataset.id, empty.id], organization_id=org.id
    ) == {dataset.id: 3}
    assert await case_generation_repo.count_pending(db, [], organization_id=org.id) == {}
    assert (
        await case_generation_repo.count_pending(db, [dataset.id], organization_id=other.id) == {}
    )

    page, total = await case_generation_repo.list_proposals(
        db, dataset.id, organization_id=org.id, generation_id=generation.id, limit=2
    )
    assert total == 3
    assert [p.input for p in page] == ["question 0", "question 1"]
    assert await case_generation_repo.list_proposals(db, dataset.id, organization_id=other.id) == (
        [],
        0,
    )

    await case_generation_repo.count_decisions(
        db, {generation.id: 2}, organization_id=org.id, accepted=True
    )
    await case_generation_repo.count_decisions(
        db, {generation.id: 1}, organization_id=org.id, accepted=False
    )
    await case_generation_repo.count_decisions(
        db, {generation.id: 5}, organization_id=other.id, accepted=True
    )
    await db.refresh(generation)
    assert (generation.accepted_count, generation.dismissed_count) == (2, 1)


async def test_generations_list_newest_first_and_finish(db) -> None:
    person = await _user(db)
    org = await _org(db, person)
    other = await _org(db, person)
    agent = await _agent(db, org)
    dataset = await _dataset(db, org)
    older, _ = await _proposals(db, org, dataset, agent, 1)
    older.created_at = _START
    newer, _ = await _proposals(db, org, dataset, agent, 1)
    await db.flush()

    listed = await case_generation_repo.list_generations(
        db, dataset.id, organization_id=org.id, limit=5
    )
    assert [g.id for g in listed] == [newer.id, older.id]
    assert await case_generation_repo.get_generation(db, newer.id, organization_id=other.id) is None

    finished = await case_generation_repo.finish_generation(
        db, newer, status="ready", finished_at=_START, proposed_count=1
    )
    assert (finished.status, finished.proposed_count) == ("ready", 1)


async def test_deleting_a_conversation_takes_its_proposals_along(db) -> None:
    person = await _user(db)
    org = await _org(db, person)
    agent = await _agent(db, org)
    dataset = await _dataset(db, org)
    run, conversation, asked = await _asked(db, org, agent, person, "Refund?", minutes=1)
    _, _, kept = await _asked(db, org, agent, person, "Other", minutes=2)
    await _proposals(
        db,
        org,
        dataset,
        agent,
        2,
        source_conversation_id=conversation.id,
        source_run_id=run.id,
        source_message_id=asked.id,
    )
    await _proposals(db, org, dataset, agent, 1, source_conversation_id=kept.conversation_id)

    other = await _org(db, person)
    assert (
        await personal_data_repo.delete_case_proposals_from_conversation(
            db, conversation.id, organization_id=other.id
        )
        == 0
    )
    assert (
        await personal_data_repo.delete_case_proposals_from_conversation(
            db, conversation.id, organization_id=org.id
        )
        == 2
    )
    assert await db.scalar(select(func.count(CaseProposal.id))) == 1


async def test_erasing_a_person_takes_the_proposals_drafted_from_them(db) -> None:
    person = await _user(db)
    bystander = await _user(db)
    org = await _org(db, person)
    agent = await _agent(db, org)
    dataset = await _dataset(db, org)
    run, conversation, _ = await _asked(db, org, agent, person, "Mine", minutes=1)
    await _proposals(db, org, dataset, agent, 1, source_conversation_id=conversation.id)
    await _proposals(db, org, dataset, agent, 1, source_run_id=run.id)
    _, theirs, _ = await _asked(db, org, agent, bystander, "Theirs", minutes=2)
    await _proposals(db, org, dataset, agent, 1, source_conversation_id=theirs.id)

    assert await personal_data_repo.delete_case_proposals_of(db, person.id) == 2
    assert await db.scalar(select(func.count(CaseProposal.id))) == 1
