"""Knowledge gaps against Postgres - what is kept, for how long, and for whom.

The claims a mocked session cannot make:

- a run's knowledge searches are stored with their best similarity, and go
  with the run and with the conversation they came from;
- a person's export carries the searches made while answering them, and their
  erasure removes them, a run with no conversation included;
- several answers become dataset cases in one version, and an answer the
  caller may not read is skipped rather than refusing the rest;
- only misses are grouped, each once per knowledge base, into topics that keep
  their ids; a knowledge base is never paired with another organization's
  search, and a topic whose searches are gone is removed;
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete, func, select

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.dataset import DatasetCase, DatasetVersion
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import (
    KnowledgeGapMember,
    KnowledgeGapTopic,
    KnowledgeSearch,
    TopicStatus,
)
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import knowledge_gap_repo
from app.schemas.dataset import DatasetCreate
from app.schemas.knowledge_gap import KnowledgeSearchRecord
from app.services.dataset import DatasetService
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.personal_data import PersonalDataService
from app.services.user import UserService

pytestmark = pytest.mark.anyio

_START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _owner(db) -> AuthContext:
    person = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=person.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=person.id, role="owner")
    )
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


async def _knowledge_base(db, ctx: AuthContext, name: str = "handbook") -> KnowledgeBase:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        name=name,
        collection_name=f"{name}_{uuid.uuid4().hex[:8]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
    )
    db.add(kb)
    await db.flush()
    return kb


async def _agent(db, ctx: AuthContext) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec={},
    )
    db.add(agent)
    await db.flush()
    return agent


async def _turn(
    db, ctx: AuthContext, agent: Agent, *, question: str = "Where do I park?"
) -> tuple[AgentRun, Message]:
    """A conversation with one question and the agent's answer to it."""
    conversation = Conversation(
        id=uuid.uuid4(), user_id=ctx.user_id, organization_id=ctx.organization_id, title="Office"
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        conversation_id=conversation.id,
        status="completed",
        started_at=_START,
        ended_at=_START + timedelta(minutes=1),
    )
    db.add(run)
    await db.flush()
    answer = None
    for role, content in (("user", question), ("assistant", "I could not find that.")):
        answer = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            run_id=run.id,
            role=role,
            content=content,
        )
        db.add(answer)
        await db.flush()
    assert answer is not None
    return run, answer


async def _searched(
    db,
    ctx: AuthContext,
    run: AgentRun,
    kb: KnowledgeBase,
    *,
    query: str = "parking",
    top_similarity: float | None = 0.12,
) -> None:
    await knowledge_gap_repo.record_searches(
        db,
        [
            KnowledgeSearchRecord(
                agent_id=run.agent_id,
                knowledge_base_ids=(kb.id,),
                query=query,
                result_count=0 if top_similarity is None else 3,
                top_similarity=top_similarity,
            )
        ],
        organization_id=ctx.organization_id,
        run_id=run.id,
        conversation_id=run.conversation_id,
    )


async def _search_count(db, run_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeSearch)
            .where(KnowledgeSearch.run_id == run_id)
        )
    ).scalar_one()


async def test_a_runs_searches_are_stored_with_their_best_similarity(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))

    await _searched(db, ctx, run, kb, query="visitor parking", top_similarity=0.21)

    stored = (
        await db.execute(select(KnowledgeSearch).where(KnowledgeSearch.run_id == run.id))
    ).scalar_one()
    assert stored.organization_id == ctx.organization_id
    assert stored.conversation_id == run.conversation_id
    assert stored.knowledge_base_ids == [kb.id]
    assert stored.query == "visitor parking"
    assert stored.top_similarity == pytest.approx(0.21)


async def test_deleting_the_run_takes_its_searches(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb)
    run_id = run.id

    await db.execute(delete(Message).where(Message.run_id == run_id))
    await db.execute(delete(AgentRun).where(AgentRun.id == run_id))

    assert await _search_count(db, run_id) == 0


async def test_deleting_the_conversation_takes_its_searches(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb)
    run_id = run.id

    await db.execute(delete(Conversation).where(Conversation.id == run.conversation_id))

    assert await _search_count(db, run_id) == 0


async def _api_run(db, ctx: AuthContext, agent: Agent, user_id: uuid.UUID) -> AgentRun:
    """A run somebody started over the HTTP API, which keeps no conversation."""
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=user_id,
        status="completed",
        surface="api",
        started_at=_START,
    )
    db.add(run)
    await db.flush()
    return run


async def test_a_persons_export_carries_the_searches_made_for_them_and_nobody_elses(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    person = await _user(db)
    person_id = person.id
    await _searched(db, ctx, await _api_run(db, ctx, agent, person_id), kb, query="their query")
    await _searched(db, ctx, await _api_run(db, ctx, agent, ctx.user_id), kb, query="not theirs")

    export = await PersonalDataService(db).export(person_id, actor_user_id=person_id)

    assert [row["query"] for row in export.knowledge_searches] == ["their query"]


async def test_erasing_a_person_removes_the_searches_of_their_api_runs(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    person = await _user(db)
    person_id = person.id
    theirs = await _api_run(db, ctx, agent, person_id)
    others = await _api_run(db, ctx, agent, ctx.user_id)
    theirs_id, others_id = theirs.id, others.id
    await _searched(db, ctx, theirs, kb)
    await _searched(db, ctx, others, kb)

    await UserService(db).delete(person_id)

    assert await _search_count(db, theirs_id) == 0
    assert await _search_count(db, others_id) == 1


# Queries about one thing point one way, about another thing another way.
_MEANINGS = {"parking": [1.0, 0.0, 0.0], "wifi": [0.0, 1.0, 0.0], "lunch": [0.0, 0.0, 1.0]}


def _meaning(query: str) -> list[float]:
    for word, vector in _MEANINGS.items():
        if word in query:
            return vector
    return [0.3, 0.3, 0.3]


@contextmanager
def _embedding() -> Iterator[MagicMock]:
    """An embedder that places a query by the topic word it contains."""
    embedder = MagicMock()
    embedder.embed_queries = MagicMock(side_effect=lambda qs: [_meaning(q) for q in qs])
    with (
        patch(
            "app.services.knowledge_gaps.embeddings_for_collection",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch("app.services.knowledge_gaps.embedder_for", return_value=embedder),
    ):
        yield embedder


async def _group(db, ctx: AuthContext, kb: KnowledgeBase) -> int:
    return await KnowledgeGapService(db).group_pending(
        organization_id=ctx.organization_id, knowledge_base_id=kb.id
    )


async def _topics(db, kb: KnowledgeBase) -> dict[uuid.UUID, list[str]]:
    rows = await db.execute(
        select(KnowledgeGapTopic.id, KnowledgeSearch.query)
        .join(KnowledgeGapMember, KnowledgeGapMember.topic_id == KnowledgeGapTopic.id)
        .join(KnowledgeSearch, KnowledgeSearch.id == KnowledgeGapMember.search_id)
        .where(KnowledgeGapTopic.knowledge_base_id == kb.id)
        .order_by(KnowledgeSearch.query)
    )
    topics: dict[uuid.UUID, list[str]] = {}
    for topic_id, query in rows.all():
        topics.setdefault(topic_id, []).append(query)
    return topics


async def test_misses_about_one_thing_share_a_topic_and_found_answers_are_left_out(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb, query="parking for visitors", top_similarity=0.1)
    await _searched(db, ctx, run, kb, query="parking permit", top_similarity=None)
    await _searched(db, ctx, run, kb, query="guest wifi", top_similarity=0.2)
    await _searched(db, ctx, run, kb, query="parking garage hours", top_similarity=0.9)

    with _embedding():
        grouped = await _group(db, ctx, kb)

    assert grouped == 3
    assert sorted((await _topics(db, kb)).values()) == [
        ["guest wifi"],
        ["parking for visitors", "parking permit"],
    ]


async def test_a_grouped_miss_is_not_embedded_again_and_a_new_one_joins_its_topic(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb, query="parking for visitors")
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)
    await _searched(db, ctx, run, kb, query="parking permit")

    with _embedding() as embedder:
        await _group(db, ctx, kb)
        nothing_left = await _group(db, ctx, kb)

    embedder.embed_queries.assert_called_once_with(["parking permit"])
    assert nothing_left == 0
    assert await _topics(db, kb) == {topic_id: ["parking for visitors", "parking permit"]}


async def test_a_dismissed_topic_keeps_its_questions_instead_of_coming_back(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb, query="lunch menu")
    with _embedding():
        await _group(db, ctx, kb)
    topic = (await db.execute(select(KnowledgeGapTopic))).scalar_one()
    topic.status = TopicStatus.DISMISSED.value
    await db.flush()
    await _searched(db, ctx, run, kb, query="lunch hours")

    with _embedding():
        await _group(db, ctx, kb)

    assert list(await _topics(db, kb)) == [topic.id]


async def test_a_collection_moved_to_another_model_starts_new_topics(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb, query="parking for visitors")
    with _embedding():
        await _group(db, ctx, kb)
    kb.embedding_model = "text-embedding-3-large"
    await db.flush()
    await _searched(db, ctx, run, kb, query="parking permit")

    with _embedding():
        await _group(db, ctx, kb)

    assert len(await _topics(db, kb)) == 2


async def test_a_search_over_two_collections_is_grouped_in_each(db) -> None:
    ctx = await _owner(db)
    handbook = await _knowledge_base(db, ctx, "handbook")
    policies = await _knowledge_base(db, ctx, "policies")
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await knowledge_gap_repo.record_searches(
        db,
        [
            KnowledgeSearchRecord(
                agent_id=run.agent_id,
                knowledge_base_ids=(handbook.id, policies.id),
                query="parking",
                result_count=0,
                top_similarity=None,
            )
        ],
        organization_id=ctx.organization_id,
        run_id=run.id,
        conversation_id=run.conversation_id,
    )

    with _embedding():
        await _group(db, ctx, handbook)
        await _group(db, ctx, policies)

    assert list((await _topics(db, handbook)).values()) == [["parking"]]
    assert list((await _topics(db, policies)).values()) == [["parking"]]


async def test_one_pass_groups_at_most_a_batch(db, monkeypatch) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    for n in range(3):
        await _searched(db, ctx, run, kb, query=f"parking {n}")
    monkeypatch.setattr("app.services.knowledge_gaps.GROUPING_BATCH", 2)

    with _embedding():
        first = await _group(db, ctx, kb)
        second = await _group(db, ctx, kb)

    assert (first, second) == (2, 1)


async def test_a_knowledge_base_is_never_paired_with_another_organizations_search(db) -> None:
    ours = await _owner(db)
    theirs = await _owner(db)
    kb = await _knowledge_base(db, ours)
    run, _ = await _turn(db, theirs, await _agent(db, theirs))
    # A search in their organization naming our knowledge base's id.
    await _searched(db, theirs, run, kb)

    waiting = await KnowledgeGapService(db).waiting_to_be_grouped()
    with _embedding() as embedder:
        grouped = await _group(db, ours, kb)

    assert (ours.organization_id, kb.id) not in waiting
    assert grouped == 0
    embedder.embed_queries.assert_not_called()


async def test_only_knowledge_bases_with_new_misses_are_waiting(db) -> None:
    ctx = await _owner(db)
    quiet = await _knowledge_base(db, ctx, "quiet")
    busy = await _knowledge_base(db, ctx, "busy")
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, quiet, query="parking", top_similarity=0.95)
    await _searched(db, ctx, run, busy, query="parking", top_similarity=0.05)

    waiting = await KnowledgeGapService(db).waiting_to_be_grouped()

    assert (ctx.organization_id, busy.id) in waiting
    assert (ctx.organization_id, quiet.id) not in waiting


async def test_a_topic_whose_searches_are_gone_is_removed(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb, query="parking")
    with _embedding():
        await _group(db, ctx, kb)
    await db.execute(delete(Conversation).where(Conversation.id == run.conversation_id))

    removed = await KnowledgeGapService(db).forget_empty_topics()

    assert removed == 1
    assert (await db.execute(select(func.count()).select_from(KnowledgeGapTopic))).scalar_one() == 0


async def test_several_answers_become_cases_in_one_version_and_foreign_ones_are_skipped(
    db,
) -> None:
    ctx = await _owner(db)
    stranger = await _owner(db)
    agent = await _agent(db, ctx)
    _, parking = await _turn(db, ctx, agent, question="Where do I park?")
    _, wifi = await _turn(db, ctx, agent, question="What is the wifi password?")
    _, theirs = await _turn(db, stranger, await _agent(db, stranger), question="Their question")
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="Office gaps"))

    version, skipped = await datasets.add_from_messages(
        ctx, dataset.id, [parking.id, theirs.id, wifi.id]
    )

    assert version is not None
    assert (version.number, version.case_count, skipped) == (1, 2, 1)
    cases = (
        (await db.execute(select(DatasetCase).where(DatasetCase.dataset_id == dataset.id)))
        .scalars()
        .all()
    )
    assert sorted(c.input for c in cases) == ["What is the wifi password?", "Where do I park?"]
    assert {c.counter_example for c in cases} == {"I could not find that."}
    assert {c.source for c in cases} == {"conversation"}


async def test_answers_none_of_which_can_be_read_add_no_version(db) -> None:
    ctx = await _owner(db)
    stranger = await _owner(db)
    _, theirs = await _turn(db, stranger, await _agent(db, stranger))
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="Office gaps"))

    version, skipped = await datasets.add_from_messages(ctx, dataset.id, [theirs.id])

    assert (version, skipped) == (None, 1)
    versions = await db.execute(
        select(func.count())
        .select_from(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
    )
    assert versions.scalar_one() == 0
