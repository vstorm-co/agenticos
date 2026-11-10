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

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.case_generation import CaseProposal
from app.db.models.intercepted_tool_call import InterceptedToolCall
from app.db.models.rag_document import DocumentStatus
from app.repositories import (
    agent_run_repo,
    case_generation_repo,
    knowledge_base_repo,
    personal_data_repo,
    rag_document_repo,
)
from tests.integration import case_generation_world as world

pytestmark = pytest.mark.anyio


async def test_questions_come_back_rated_down_first_from_this_agent_only(db) -> None:
    person = await world.user(db)
    org = await world.org(db, person)
    agent = await world.agent(db, org)
    other_agent = await world.agent(db, org)
    await world.asked(db, org, agent, person, "Oldest", minutes=1)
    await world.asked(db, org, agent, person, "Newest", minutes=30)
    await world.asked(
        db, org, agent, person, "Disliked", minutes=10, rating=-1, comment="Wrong window"
    )
    await world.asked(db, org, agent, person, "Liked", minutes=20, rating=1, comment="Great")
    await world.asked(db, org, other_agent, person, "Someone else's", minutes=40, rating=-1)

    questions = await agent_run_repo.questions_asked(
        db, organization_id=org.id, agent_id=agent.id, limit=10
    )

    assert [q.content for q in questions] == ["Disliked", "Newest", "Liked", "Oldest"]
    assert questions[0].rated_down is True
    assert questions[0].comment == "Wrong window"
    assert questions[2].rated_down is False
    assert questions[2].comment is None


async def test_questions_come_from_production_traffic_only(db) -> None:
    """An eval answered a test, not a person: a case drafted from it tests the agent on itself."""
    person = await world.user(db)
    org = await world.org(db, person)
    agent = await world.agent(db, org)
    await world.asked(db, org, agent, person, "Asked by a person", minutes=1)
    await world.asked(db, org, agent, person, "An eval case", minutes=2, rating=-1, surface="eval")
    isolated, _, _ = await world.asked(
        db, org, agent, person, "Run isolated", minutes=3, rating=-1, surface="api"
    )
    db.add(
        InterceptedToolCall(
            organization_id=org.id,
            run_id=isolated.id,
            sequence=0,
            tool_call_id="call-1",
            tool_name="send_email",
            tool_id="email.send_email",
            outcome="blocked",
            reason="writes",
        )
    )
    await db.flush()

    questions = await agent_run_repo.questions_asked(
        db, organization_id=org.id, agent_id=agent.id, limit=10
    )

    assert [q.content for q in questions] == ["Asked by a person"]


@pytest.mark.security
async def test_questions_never_cross_into_another_organization(db) -> None:
    person = await world.user(db)
    mine = await world.org(db, person)
    theirs = await world.org(db, person)
    their_agent = await world.agent(db, theirs)
    await world.asked(db, theirs, their_agent, person, "Their secret question", minutes=1)

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
    person = await world.user(db)
    org = await world.org(db, person)
    agent = await world.agent(db, org)
    for minute in range(5):
        await world.asked(db, org, agent, person, f"q{minute}", minutes=minute)

    questions = await agent_run_repo.questions_asked(
        db, organization_id=org.id, agent_id=agent.id, limit=2
    )

    assert [q.content for q in questions] == ["q4", "q3"]


async def test_collections_and_documents_are_read_through_the_organization(db) -> None:
    person = await world.user(db)
    org = await world.org(db, person)
    other = await world.org(db, person)
    first = await world.collection(db, org)
    second = await world.collection(db, org)
    foreign = await world.collection(db, other)
    personal = await world.collection(db, None)
    done = await world.document(db, first, DocumentStatus.DONE, "handbook.md")
    await world.document(db, first, DocumentStatus.ERROR, "broken.md")
    await world.document(db, first, DocumentStatus.PROCESSING, "parsing.md")
    later = await world.document(db, second, DocumentStatus.DONE, "faq.md")
    await world.document(db, foreign, DocumentStatus.DONE, "theirs.md")

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
    person = await world.user(db)
    org = await world.org(db, person)
    agent = await world.agent(db, org)
    dataset = await world.dataset(db, org)
    _, proposals = await world.proposals(db, org, dataset, agent, 2)
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


@pytest.mark.security
async def test_taking_and_counting_stay_inside_the_dataset_and_tenant(db) -> None:
    person = await world.user(db)
    org = await world.org(db, person)
    other = await world.org(db, person)
    agent = await world.agent(db, org)
    dataset = await world.dataset(db, org)
    empty = await world.dataset(db, org)
    generation, proposals = await world.proposals(db, org, dataset, agent, 3)

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
    person = await world.user(db)
    org = await world.org(db, person)
    other = await world.org(db, person)
    agent = await world.agent(db, org)
    dataset = await world.dataset(db, org)
    older, _ = await world.proposals(db, org, dataset, agent, 1)
    older.created_at = world.START
    newer, _ = await world.proposals(db, org, dataset, agent, 1)
    await db.flush()

    listed = await case_generation_repo.list_generations(
        db, dataset.id, organization_id=org.id, limit=5
    )
    assert [g.id for g in listed] == [newer.id, older.id]
    assert await case_generation_repo.get_generation(db, newer.id, organization_id=other.id) is None

    finished = await case_generation_repo.finish_generation(
        db, newer, status="ready", finished_at=world.START, proposed_count=1
    )
    assert (finished.status, finished.proposed_count) == ("ready", 1)


async def test_deleting_a_conversation_takes_its_proposals_along(db) -> None:
    person = await world.user(db)
    org = await world.org(db, person)
    agent = await world.agent(db, org)
    dataset = await world.dataset(db, org)
    run, conversation, asked = await world.asked(db, org, agent, person, "Refund?", minutes=1)
    _, _, kept = await world.asked(db, org, agent, person, "Other", minutes=2)
    await world.proposals(
        db,
        org,
        dataset,
        agent,
        2,
        source_conversation_id=conversation.id,
        source_run_id=run.id,
        source_message_id=asked.id,
    )
    await world.proposals(db, org, dataset, agent, 1, source_conversation_id=kept.conversation_id)

    other = await world.org(db, person)
    await personal_data_repo.unlink_dataset_cases_from_conversation(
        db, conversation.id, organization_id=other.id
    )
    assert await db.scalar(select(func.count(CaseProposal.id))) == 3

    await personal_data_repo.unlink_dataset_cases_from_conversation(
        db, conversation.id, organization_id=org.id
    )
    assert await db.scalar(select(func.count(CaseProposal.id))) == 1


async def test_erasing_a_person_takes_the_proposals_drafted_from_them(db) -> None:
    person = await world.user(db)
    bystander = await world.user(db)
    org = await world.org(db, person)
    agent = await world.agent(db, org)
    dataset = await world.dataset(db, org)
    run, conversation, _ = await world.asked(db, org, agent, person, "Mine", minutes=1)
    await world.proposals(db, org, dataset, agent, 1, source_conversation_id=conversation.id)
    await world.proposals(db, org, dataset, agent, 1, source_run_id=run.id)
    _, theirs, _ = await world.asked(db, org, agent, bystander, "Theirs", minutes=2)
    await world.proposals(db, org, dataset, agent, 1, source_conversation_id=theirs.id)

    assert await personal_data_repo.delete_case_proposals_of(db, person.id) == 2
    assert await db.scalar(select(func.count(CaseProposal.id))) == 1


async def test_a_question_typed_in_someone_else_s_thread_is_its_author_s(db) -> None:
    """In a project chat the thread's starter is not who asked, so the author's
    export lists the draft and erasing the author takes it."""
    starter = await world.user(db)
    member = await world.user(db)
    org = await world.org(db, starter)
    agent = await world.agent(db, org)
    dataset = await world.dataset(db, org)
    _, _, asked = await world.asked(db, org, agent, starter, "Ours", minutes=1, author=member)
    _, [drafted] = await world.proposals(db, org, dataset, agent, 1, source_message_id=asked.id)

    assert [p.id for p in await personal_data_repo.case_proposals_from(db, member.id)] == [
        drafted.id
    ]
    assert await personal_data_repo.case_proposals_from(db, starter.id) == []
    assert await personal_data_repo.delete_case_proposals_of(db, member.id) == 1
    assert await db.scalar(select(func.count(CaseProposal.id))) == 0
