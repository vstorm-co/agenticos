"""Knowledge gaps against Postgres - what is kept, for how long, and for whom.

The claims a mocked session cannot make:

- a run's knowledge searches are stored with their best similarity, and go
  with the run and with the conversation they came from;
- a person's export carries the searches made while answering them, and their
  erasure removes them, a run with no conversation included;
- several answers become dataset cases in one version, and an answer the
  caller may not read is skipped rather than refusing the rest;
- a topic is read with its count, examples, agents and questions - each with
  what the person asked, the answer and the comment on it - and is refused as
  missing to another organization, to a caller who cannot read its knowledge
  base, and outright to a caller without `runs:view`;
- a topic's questions become dataset cases in one action;
- a draft of the missing passage is one run of the drafting agent, refused
  while the organization has AI assistance off, and is kept on the topic for a
  person - with credentials redacted and answers outside the topic dropped;
- only misses are grouped, each once per knowledge base, into topics that keep
  their ids; a knowledge base is never paired with another organization's
  search, and a topic whose searches are gone is removed;
"""

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.capabilities.knowledge import KnowledgeSearchLog
from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AiAssistanceDisabledError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    SystemAgentRunError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message, ToolCall
from app.db.models.dataset import DatasetCase, DatasetVersion
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import (
    GapSignal,
    KnowledgeGapMember,
    KnowledgeGapTopic,
    KnowledgeSearch,
    TopicStatus,
)
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.rag_document import RAGDocument
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.db.models.user import User
from app.repositories import knowledge_gap_repo, personal_data_repo
from app.schemas.dataset import DatasetCreate
from app.schemas.knowledge_gap import (
    KnowledgeGapDraft,
    KnowledgeGapReport,
    KnowledgeGapSource,
    KnowledgeSearchRecord,
)
from app.services.agent_runner import AgentRunnerService, PreparedRun
from app.services.dataset import DatasetService
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.personal_data import PersonalDataService
from app.services.system_agent_runner import SystemAgentResult
from app.services.user import UserService

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("knowledge_search")]

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


async def _knowledge_base(
    db, ctx: AuthContext, name: str = "handbook", *, scope: str = "org"
) -> KnowledgeBase:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        name=name,
        collection_name=f"{name}_{uuid.uuid4().hex[:8]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        scope=scope,
        visibility="org",
        owner_user_id=ctx.user_id,
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


async def test_a_shared_chat_carries_each_members_searches_to_their_own_export_alone(db) -> None:
    """A project chat one member started and another continued holds both their
    questions; each is exported and erased with the run that asked it."""
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    person = await _user(db)
    person_id = person.id
    conversation = Conversation(
        id=uuid.uuid4(), user_id=person_id, organization_id=ctx.organization_id, title="Team"
    )
    db.add(conversation)
    await db.flush()
    runs = {}
    for name, user_id in (("theirs", person_id), ("colleagues", ctx.user_id)):
        runs[name] = AgentRun(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            user_id=user_id,
            conversation_id=conversation.id,
            status="completed",
            started_at=_START,
        )
        db.add(runs[name])
        await db.flush()
        await _searched(db, ctx, runs[name], kb, query=f"{name} query")

    export = await PersonalDataService(db).export(person_id, actor_user_id=person_id)
    removed = await personal_data_repo.purge_knowledge_searches_of(db, person_id)

    assert [row["query"] for row in export.knowledge_searches] == ["theirs query"]
    assert removed == 1
    assert await _search_count(db, runs["colleagues"].id) == 1


async def _a_run_that_searched(engine) -> tuple[async_sessionmaker, AgentRun, PreparedRun]:
    """A run its starter started, one search waiting in its log, the run's own session."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as setup:
        ctx = await _owner(setup)
        kb = await _knowledge_base(setup, ctx)
        run, _ = await _turn(setup, ctx, await _agent(setup, ctx))
        run.user_id = (await _user(setup)).id
        await setup.commit()
    log = KnowledgeSearchLog(agent_id=run.agent_id, collections={kb.collection_name: (kb.id,)})
    log.record("parking", [kb.collection_name], [])
    prepared = PreparedRun(
        run=run,
        agent=MagicMock(),
        spec=AgentSpec(name="Clerk"),
        built=MagicMock(),
        approvals=MagicMock(),
        knowledge_searches=log,
    )
    return factory, run, prepared


async def test_a_search_written_while_its_starter_is_erased_is_dropped(engine) -> None:
    """The erasure holds the person's lock from its purge to its commit; a search
    written in that window would be theirs, after the purge, with nothing to find it."""
    factory, run, prepared = await _a_run_that_searched(engine)
    erasing = factory()
    try:
        await PersonalDataService(erasing).purge(run.user_id)
        async with factory() as session:
            await AgentRunnerService(session)._write_knowledge_searches(prepared)
            await session.commit()
    finally:
        await erasing.rollback()
        await erasing.close()

    async with factory() as session:
        assert await _search_count(session, run.id) == 0


async def test_a_search_for_a_starter_whose_account_is_gone_is_dropped(engine) -> None:
    factory, run, prepared = await _a_run_that_searched(engine)
    async with factory() as session:
        await session.execute(delete(User).where(User.id == run.user_id))
        await session.commit()

    async with factory() as session:
        await AgentRunnerService(session)._write_knowledge_searches(prepared)
        await session.commit()
        assert await _search_count(session, run.id) == 0


async def test_a_search_for_a_starter_who_is_here_is_written(engine) -> None:
    factory, run, prepared = await _a_run_that_searched(engine)

    async with factory() as session:
        await AgentRunnerService(session)._write_knowledge_searches(prepared)
        await session.commit()
        assert await _search_count(session, run.id) == 1


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


async def test_two_passes_over_one_knowledge_base_at_once_place_each_question_once(
    db, engine
) -> None:
    """A regroup overlapping the scheduled pass waits for it, rather than reading the
    misses it has not committed yet and putting each in a second topic."""
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb, query="parking permit")
    await _searched(db, ctx, run, kb, query="guest wifi")
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    first_placed = asyncio.Event()

    async def group(*, first: bool) -> int:
        async with factory() as session:
            if not first:
                await first_placed.wait()
            placed = await _group(session, ctx, kb)
            if first:
                first_placed.set()
                await asyncio.sleep(0.3)
            await session.commit()
            return placed

    with _embedding():
        placed = await asyncio.gather(group(first=True), group(first=False))

    assert placed == [2, 0]
    async with factory() as fresh:
        assert sorted((await _topics(fresh, kb)).values()) == [["guest wifi"], ["parking permit"]]


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


async def test_an_answer_the_dataset_holds_or_the_batch_names_twice_is_skipped(db) -> None:
    ctx = await _owner(db)
    agent = await _agent(db, ctx)
    _, parking = await _turn(db, ctx, agent, question="Where do I park?")
    _, wifi = await _turn(db, ctx, agent, question="What is the wifi password?")
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="Office gaps"))
    await datasets.add_from_messages(ctx, dataset.id, [parking.id])

    version, skipped = await datasets.add_from_messages(
        ctx, dataset.id, [parking.id, wifi.id, wifi.id]
    )

    assert version is not None
    assert (version.number, version.case_count, skipped) == (2, 2, 2)


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


async def _member(db, ctx: AuthContext, role: OrgRoleName) -> AuthContext:
    person = await _user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=ctx.organization_id, user_id=person.id, role=role
        )
    )
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=ctx.organization_id, role=role.value)


async def _a_topic(db, ctx: AuthContext) -> tuple[KnowledgeBase, Agent, uuid.UUID]:
    """A knowledge base with one topic of two parking questions, one rated down."""
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    first, first_answer = await _turn(db, ctx, agent, question="Where can visitors park?")
    second, _ = await _turn(db, ctx, agent, question="Do I need a parking permit?")
    await _searched(db, ctx, first, kb, query="visitor parking")
    await _searched(db, ctx, second, kb, query="parking permit")
    db.add(
        MessageRating(
            message_id=first_answer.id, user_id=ctx.user_id, rating=-1, comment="No parking info"
        )
    )
    await db.flush()
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)
    return kb, agent, topic_id


async def test_a_topic_reads_with_its_questions_and_the_answers_they_got(db) -> None:
    ctx = await _owner(db)
    kb, agent, topic_id = await _a_topic(db, ctx)
    service = KnowledgeGapService(db)

    listed = await service.list_for_knowledge_base(ctx, kb.id)
    detail = await service.read(ctx, topic_id)

    [topic] = listed.items
    assert (listed.total, listed.ungrouped) == (1, 0)
    assert topic.label in {"visitor parking", "parking permit"}
    assert topic.question_count == 2
    assert sorted(topic.examples) == ["parking permit", "visitor parking"]
    assert [a.name for a in topic.agents] == [agent.name]
    by_query = {q.query: q for q in detail.questions}
    assert by_query["visitor parking"].question == "Where can visitors park?"
    assert by_query["visitor parking"].down_rating_comment == "No parking info"
    assert by_query["visitor parking"].answer_message_id is not None
    assert by_query["parking permit"].down_rating_comment is None


async def test_the_organizations_gaps_leave_out_a_knowledge_base_the_caller_cannot_read(
    db,
) -> None:
    ctx = await _owner(db)
    kb, _, _ = await _a_topic(db, ctx)
    private = await _knowledge_base(db, ctx, "private", scope="personal")
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, private, query="lunch")
    with _embedding():
        await _group(db, ctx, private)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)

    owners = await KnowledgeGapService(db).list_for_organization(ctx)
    operators = await KnowledgeGapService(db).list_for_organization(operator)

    assert {t.knowledge_base_name for t in owners.items} == {kb.name, private.name}
    assert [t.knowledge_base_id for t in operators.items] == [kb.id]
    assert [(c.knowledge_base_name, c.topics, c.questions) for c in owners.by_knowledge_base] == [
        (kb.name, 1, 2),
        (private.name, 1, 1),
    ]
    assert [c.knowledge_base_id for c in operators.by_knowledge_base] == [kb.id]


async def test_misses_no_pass_has_grouped_yet_are_counted_before_any_topic_exists(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    private = await _knowledge_base(db, ctx, "private", scope="personal")
    agent = await _agent(db, ctx)
    run, _ = await _turn(db, ctx, agent)
    await _searched(db, ctx, run, kb, query="parking permit")
    await _searched(db, ctx, run, private, query="lunch menu")
    await _searched(db, ctx, run, kb, query="parking garage hours", top_similarity=0.9)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)

    owners = await KnowledgeGapService(db).list_for_organization(ctx)
    operators = await KnowledgeGapService(db).list_for_organization(operator)
    agents = await KnowledgeGapService(db).list_for_agent(ctx, agent.id)
    others = await KnowledgeGapService(db).list_for_agent(ctx, (await _agent(db, ctx)).id)

    assert (owners.total, owners.ungrouped) == (0, 2)
    assert (operators.total, operators.ungrouped) == (0, 1)
    assert (agents.total, agents.ungrouped) == (0, 2)
    assert (others.total, others.ungrouped) == (0, 0)


async def test_an_agents_gaps_hold_only_its_own_questions(db) -> None:
    ctx = await _owner(db)
    kb, agent, _ = await _a_topic(db, ctx)
    other = await _agent(db, ctx)
    run, _ = await _turn(db, ctx, other)
    await _searched(db, ctx, run, kb, query="parking garage")
    with _embedding():
        await _group(db, ctx, kb)

    mine = await KnowledgeGapService(db).list_for_agent(ctx, agent.id)
    theirs = await KnowledgeGapService(db).list_for_agent(ctx, other.id)

    assert [t.question_count for t in mine.items] == [2]
    assert [t.question_count for t in theirs.items] == [1]


async def test_another_organizations_topic_and_knowledge_base_read_as_missing(db) -> None:
    ours = await _owner(db)
    theirs = await _owner(db)
    kb, agent, topic_id = await _a_topic(db, theirs)
    dataset = await DatasetService(db).create(ours, DatasetCreate(name="Ours"))
    service = KnowledgeGapService(db)

    for attempt in (
        service.read(ours, topic_id),
        service.list_for_knowledge_base(ours, kb.id),
        service.list_for_agent(ours, agent.id),
        service.set_status(ours, topic_id, "dismissed"),
        service.add_to_dataset(ours, topic_id, dataset.id),
        service.regroup(ours, kb.id),
    ):
        with pytest.raises(NotFoundError):
            await attempt


async def test_a_caller_without_runs_view_is_refused_even_on_a_collection_they_read(db) -> None:
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    member = await _member(db, ctx, OrgRoleName.MEMBER)

    with pytest.raises(AuthorizationError):
        await KnowledgeGapService(db).list_for_knowledge_base(member, kb.id)
    with pytest.raises(AuthorizationError):
        await KnowledgeGapService(db).read(member, topic_id)


async def test_a_caller_who_cannot_read_the_knowledge_base_cannot_read_its_topics(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx, "private", scope="personal")
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb, query="parking")
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)

    with pytest.raises(NotFoundError):
        await KnowledgeGapService(db).list_for_knowledge_base(operator, kb.id)
    with pytest.raises(NotFoundError):
        await KnowledgeGapService(db).read(operator, topic_id)
    assert (await KnowledgeGapService(db).list_for_agent(operator, run.agent_id)).items == []


async def test_an_operator_reads_gaps_but_cannot_dismiss_them(db) -> None:
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)
    service = KnowledgeGapService(db)

    assert (await service.list_for_knowledge_base(operator, kb.id)).total == 1
    with pytest.raises(NotFoundError):
        await service.set_status(operator, topic_id, "dismissed")


@pytest.mark.security
async def test_an_edit_grant_on_the_knowledge_base_lets_an_operator_dismiss_its_topics(
    db,
) -> None:
    ctx = await _owner(db)
    kb, agent, topic_id = await _a_topic(db, ctx)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)
    service = KnowledgeGapService(db)

    [before] = (await service.list_for_agent(operator, agent.id)).items
    [owners] = (await service.list_for_agent(ctx, agent.id)).items
    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            subject_user_id=operator.user_id,
            resource_type="collection",
            resource_id=kb.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()
    [after] = (await service.list_for_agent(operator, agent.id)).items
    dismissed = await service.set_status(operator, topic_id, "dismissed")

    assert (before.can_edit, owners.can_edit, after.can_edit) == (False, True, True)
    assert dismissed.status == "dismissed" and dismissed.can_edit
    assert [(a.slug, a.has_avatar) for a in after.agents] == [(agent.slug, False)]


@pytest.mark.security
async def test_regrouping_is_offered_to_whoever_may_change_the_knowledge_base(db) -> None:
    ctx = await _owner(db)
    kb, agent, _ = await _a_topic(db, ctx)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)
    service = KnowledgeGapService(db)

    before = await service.list_for_knowledge_base(operator, kb.id)
    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            subject_user_id=operator.user_id,
            resource_type="collection",
            resource_id=kb.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()
    after = await service.list_for_knowledge_base(operator, kb.id)
    owners = await service.list_for_knowledge_base(ctx, kb.id)
    agents = await service.list_for_agent(ctx, agent.id)

    assert (before.can_regroup, after.can_regroup, owners.can_regroup) == (False, True, True)
    assert agents.can_regroup is False
    with patch("app.services.knowledge_gaps.spawn_after_commit") as spawn:
        await service.regroup(operator, kb.id)
    spawn.call_args.args[1].close()


async def test_dismissing_a_topic_and_reopening_it(db) -> None:
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    service = KnowledgeGapService(db)

    dismissed = await service.set_status(ctx, topic_id, "dismissed")
    hidden = await service.list_for_knowledge_base(ctx, kb.id, status="open")
    reopened = await service.set_status(ctx, topic_id, "open")

    assert dismissed.status == "dismissed" and dismissed.dismissed_at is not None
    assert hidden.items == []
    assert reopened.status == "open" and reopened.dismissed_at is None


async def test_a_topics_questions_become_cases_of_a_dataset_in_one_version(db) -> None:
    ctx = await _owner(db)
    _, _, topic_id = await _a_topic(db, ctx)
    dataset = await DatasetService(db).create(ctx, DatasetCreate(name="Parking"))

    added = await KnowledgeGapService(db).add_to_dataset(ctx, topic_id, dataset.id)

    assert (added.version, added.added, added.skipped) == (1, 2, 0)
    cases = (
        (await db.execute(select(DatasetCase).where(DatasetCase.dataset_id == dataset.id)))
        .scalars()
        .all()
    )
    assert sorted(c.input for c in cases) == [
        "Do I need a parking permit?",
        "Where can visitors park?",
    ]
    assert {c.note for c in cases} == {"No parking info", None}
    assert {c.asked_by_user_id for c in cases} == {ctx.user_id}
    assert {c.noted_by_user_id for c in cases} == {ctx.user_id, None}


async def test_a_question_asked_over_the_api_has_no_answer_to_keep_and_is_skipped(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    await _searched(db, ctx, await _api_run(db, ctx, agent, ctx.user_id), kb, query="parking")
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)
    dataset = await DatasetService(db).create(ctx, DatasetCreate(name="Parking"))

    added = await KnowledgeGapService(db).add_to_dataset(ctx, topic_id, dataset.id)

    assert (added.version, added.added, added.skipped) == (None, 0, 1)


async def test_a_raised_threshold_counts_what_was_a_hit_and_waits_for_grouping(
    db, monkeypatch
) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, kb, query="parking", top_similarity=0.45)

    before = await KnowledgeGapService(db).list_for_knowledge_base(ctx, kb.id)
    monkeypatch.setattr("app.core.config.settings.KNOWLEDGE_GAP_MIN_SIMILARITY", 0.5)
    after = await KnowledgeGapService(db).list_for_knowledge_base(ctx, kb.id)

    assert (before.total, before.ungrouped) == (0, 0)
    assert (after.total, after.ungrouped) == (0, 1)


async def test_a_topic_none_of_whose_questions_count_any_more_reads_as_missing(
    db, monkeypatch
) -> None:
    ctx = await _owner(db)
    _, _, topic_id = await _a_topic(db, ctx)
    monkeypatch.setattr("app.core.config.settings.KNOWLEDGE_GAP_MIN_SIMILARITY", 0.0)

    with pytest.raises(NotFoundError):
        await KnowledgeGapService(db).read(ctx, topic_id)


async def test_regrouping_a_knowledge_base_starts_its_pass_after_the_commit(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)

    with patch("app.services.knowledge_gaps.spawn_after_commit") as spawn:
        await KnowledgeGapService(db).regroup(ctx, kb.id)

    spawn.assert_called_once()
    assert spawn.call_args.kwargs["name"] == f"group-knowledge-gaps-{kb.id}"
    spawn.call_args.args[1].close()


async def test_answers_that_would_pass_the_case_ceiling_are_refused_before_any_lock(
    db, monkeypatch
) -> None:
    ctx = await _owner(db)
    agent = await _agent(db, ctx)
    _, first = await _turn(db, ctx, agent)
    _, second = await _turn(db, ctx, agent)
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="Small"))
    monkeypatch.setattr("app.services.dataset.MAX_CASES", 1)

    with (
        patch.object(DatasetService, "_locked", new=AsyncMock()) as locked,
        pytest.raises(BadRequestError),
    ):
        await datasets.add_from_messages(ctx, dataset.id, [first.id, second.id])

    locked.assert_not_awaited()


async def _found(db, answer: Message, query: str, result: str) -> None:
    db.add(
        ToolCall(
            id=uuid.uuid4(),
            message_id=answer.id,
            tool_call_id=f"call-{uuid.uuid4().hex[:6]}",
            tool_name="search_documents",
            args={"query": query},
            result=result,
            status="completed",
            started_at=_START,
        )
    )
    await db.flush()


@contextmanager
def _drafter(output: KnowledgeGapDraft, run: AgentRun) -> Iterator[AsyncMock]:
    run_it = AsyncMock(return_value=SystemAgentResult(output=output, run=run))
    with patch("app.services.knowledge_gaps.SystemAgentRunner.run", new=run_it):
        yield run_it


async def _document(db, ctx: AuthContext, kb: KnowledgeBase, filename: str) -> RAGDocument:
    document = RAGDocument(
        id=uuid.uuid4(),
        collection_name=kb.collection_name,
        filename=filename,
        filesize=10,
        filetype="pdf",
        organization_id=kb.organization_id,
        knowledge_base_id=kb.id,
    )
    db.add(document)
    await db.flush()
    return document


async def test_a_draft_is_not_kept_when_an_asker_was_erased_while_it_was_written(db) -> None:
    ctx = await _owner(db)
    _, agent, topic_id = await _a_topic(db, ctx)
    drafting_run, _ = await _turn(db, ctx, agent)
    present = AsyncMock(return_value=set())

    with (
        _drafter(
            KnowledgeGapDraft(title="Parking", content="Level -2.", documents=[], questions=[1]),
            drafting_run,
        ),
        patch.object(personal_data_repo, "present_among", new=present),
        pytest.raises(BadRequestError, match="Draft the topic again"),
    ):
        await KnowledgeGapService(db).draft(ctx, topic_id)

    assert set(present.await_args.args[1]) == {ctx.user_id}
    detail = await KnowledgeGapService(db).read(ctx, topic_id)
    assert detail.draft is None


async def test_a_draft_cites_only_the_documents_and_questions_it_was_shown(db) -> None:
    ctx = await _owner(db)
    kb, agent, topic_id = await _a_topic(db, ctx)
    garage = await _document(db, ctx, kb, "garage.pdf")
    first_answer = (
        (await db.execute(select(Message).where(Message.content == "I could not find that.")))
        .scalars()
        .first()
    )
    assert first_answer is not None
    await _found(
        db, first_answer, "visitor parking", "[1] Source: garage.pdf, page 2 (score: 0.210)\nHours"
    )
    drafting_run, _ = await _turn(db, ctx, agent)

    with _drafter(
        KnowledgeGapDraft(
            title="Visitor parking",
            content="Visitors park on level [level]. Key: ghp_" + "a" * 36,
            documents=[1, 4],
            questions=[1, 2, 7],
        ),
        drafting_run,
    ) as run_it:
        await KnowledgeGapService(db).draft(ctx, topic_id)

    drafted = await KnowledgeGapService(db).read(ctx, topic_id)
    prompt = run_it.await_args.kwargs["prompt"]
    assert kb.name in prompt
    assert "1. garage.pdf" in prompt
    assert "Where can visitors park?" in prompt
    assert "No parking info" in prompt
    assert run_it.await_args.kwargs["key"] == "knowledge_gap_drafter"
    assert drafted.draft is not None
    assert drafted.draft.title == "Visitor parking"
    assert "ghp_" not in drafted.draft.content
    documents = [s for s in drafted.draft.sources if s.kind == "document"]
    assert [(d.id, d.label) for d in documents] == [(garage.id, "garage.pdf")]
    assert {s.label for s in drafted.draft.sources if s.kind == "question"} == {
        "visitor parking",
        "parking permit",
    }
    assert drafted.draft.unverified == 2
    assert drafted.draft.run_id == drafting_run.id
    listed = await KnowledgeGapService(db).list_for_knowledge_base(ctx, kb.id)
    assert [t.has_draft for t in listed.items] == [True]


async def test_with_ai_assistance_off_no_draft_is_asked_for_or_kept(db) -> None:
    ctx = await _owner(db)
    _, _, topic_id = await _a_topic(db, ctx)
    organization = await db.get(Organization, ctx.organization_id)
    organization.ai_assistance_enabled = False
    await db.flush()

    with pytest.raises(AiAssistanceDisabledError):
        await KnowledgeGapService(db).draft(ctx, topic_id)

    topic = await db.get(KnowledgeGapTopic, topic_id)
    assert topic is not None and topic.draft_content is None
    drafter_runs = await db.execute(
        select(func.count()).select_from(AgentRun).where(AgentRun.surface == "eval")
    )
    assert drafter_runs.scalar_one() == 0


async def test_a_drafting_run_that_ends_without_an_answer_keeps_no_draft(db) -> None:
    ctx = await _owner(db)
    _, _, topic_id = await _a_topic(db, ctx)
    refused = AsyncMock(
        side_effect=SystemAgentRunError(
            message="budget", run_id=uuid.uuid4(), status="budget_exceeded"
        )
    )

    with (
        patch("app.services.knowledge_gaps.SystemAgentRunner.run", new=refused),
        pytest.raises(SystemAgentRunError),
    ):
        await KnowledgeGapService(db).draft(ctx, topic_id)

    topic = await db.get(KnowledgeGapTopic, topic_id)
    assert topic is not None and topic.draft_content is None


async def test_another_organizations_topic_cannot_be_drafted_or_reported_on(db) -> None:
    ours = await _owner(db)
    theirs = await _owner(db)
    _, _, topic_id = await _a_topic(db, theirs)
    service = KnowledgeGapService(db)

    with pytest.raises(NotFoundError):
        await service.draft(ours, topic_id)
    with pytest.raises(NotFoundError):
        await service.record_draft(
            ours, KnowledgeGapReport(topic_id=topic_id, title="x", content="y")
        )


@pytest.mark.security
async def test_a_reader_of_the_knowledge_base_cannot_replace_its_topic_s_draft(db) -> None:
    ctx = await _owner(db)
    _, _, topic_id = await _a_topic(db, ctx)
    service = KnowledgeGapService(db)
    await service.record_draft(
        ctx, KnowledgeGapReport(topic_id=topic_id, title="Parking", content="Level [n].")
    )
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)
    run_it = AsyncMock()

    with (
        patch("app.services.knowledge_gaps.SystemAgentRunner.run", new=run_it),
        pytest.raises(NotFoundError),
    ):
        await service.draft(operator, topic_id)
    with pytest.raises(NotFoundError):
        await service.record_draft(
            operator, KnowledgeGapReport(topic_id=topic_id, title="Mine", content="Mine.")
        )

    run_it.assert_not_awaited()
    topic = await db.get(KnowledgeGapTopic, topic_id)
    assert topic is not None
    assert (topic.draft_title, topic.drafted_by_user_id) == ("Parking", ctx.user_id)


async def test_a_report_keeps_only_sources_it_can_verify(db) -> None:
    ctx = await _owner(db)
    stranger = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    other_kb = await _knowledge_base(db, ctx, "other")
    theirs_kb = await _knowledge_base(db, stranger, "theirs")
    mine = await _document(db, ctx, kb, "handbook.pdf")
    elsewhere = await _document(db, ctx, other_kb, "other.pdf")
    foreign = await _document(db, stranger, theirs_kb, "theirs.pdf")
    run, _ = await _turn(db, ctx, await _agent(db, ctx))
    await _searched(db, ctx, run, other_kb, query="lunch")
    other_search = (
        await db.execute(select(KnowledgeSearch.id).where(KnowledgeSearch.query == "lunch"))
    ).scalar_one()
    question = next(iter((await KnowledgeGapService(db).read(ctx, topic_id)).questions)).search_id

    await KnowledgeGapService(db).record_draft(
        ctx,
        KnowledgeGapReport(
            topic_id=topic_id,
            title="Parking",
            content="Text",
            sources=[
                KnowledgeGapSource(kind="document", id=mine.id),
                KnowledgeGapSource(kind="document", id=elsewhere.id),
                KnowledgeGapSource(kind="document", id=foreign.id),
                KnowledgeGapSource(kind="question", id=question),
                KnowledgeGapSource(kind="question", id=other_search),
                KnowledgeGapSource(kind="document", id=uuid.uuid4()),
            ],
        ),
    )

    detail = await KnowledgeGapService(db).read(ctx, topic_id)
    assert detail.draft is not None
    assert [(s.kind, s.id) for s in detail.draft.sources] == [
        ("document", mine.id),
        ("question", question),
    ]
    assert detail.draft.unverified == 4
    assert detail.draft.run_id is None


async def test_a_draft_keeps_at_most_twelve_sources(db) -> None:
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    documents = [await _document(db, ctx, kb, f"doc{n}.pdf") for n in range(15)]

    await KnowledgeGapService(db).record_draft(
        ctx,
        KnowledgeGapReport(
            topic_id=topic_id,
            title="Parking",
            content="Text",
            sources=[KnowledgeGapSource(kind="document", id=d.id) for d in documents],
        ),
    )

    detail = await KnowledgeGapService(db).read(ctx, topic_id)
    assert detail.draft is not None
    assert len(detail.draft.sources) == 12
    assert detail.draft.unverified == 0


async def test_a_source_deleted_after_the_draft_is_left_out_and_the_rest_stays(db) -> None:
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    kept = await _document(db, ctx, kb, "kept.pdf")
    gone = await _document(db, ctx, kb, "gone.pdf")
    await KnowledgeGapService(db).record_draft(
        ctx,
        KnowledgeGapReport(
            topic_id=topic_id,
            title="Parking",
            content="Text",
            sources=[
                KnowledgeGapSource(kind="document", id=kept.id),
                KnowledgeGapSource(kind="document", id=gone.id),
            ],
        ),
    )
    await db.delete(gone)
    await db.flush()

    detail = await KnowledgeGapService(db).read(ctx, topic_id)

    assert detail.draft is not None
    assert [s.label for s in detail.draft.sources] == ["kept.pdf"]


async def test_a_topic_none_of_whose_questions_count_any_more_cannot_be_drafted(
    db, monkeypatch
) -> None:
    ctx = await _owner(db)
    _, _, topic_id = await _a_topic(db, ctx)
    monkeypatch.setattr("app.core.config.settings.KNOWLEDGE_GAP_MIN_SIMILARITY", 0.0)

    with (
        patch("app.services.knowledge_gaps.SystemAgentRunner.run", new=AsyncMock()) as run_it,
        pytest.raises(NotFoundError),
    ):
        await KnowledgeGapService(db).draft(ctx, topic_id)

    run_it.assert_not_awaited()


async def test_a_draft_resting_only_on_questions_reads_back_without_documents(db) -> None:
    ctx = await _owner(db)
    _, _, topic_id = await _a_topic(db, ctx)
    question = next(iter((await KnowledgeGapService(db).read(ctx, topic_id)).questions))

    await KnowledgeGapService(db).record_draft(
        ctx,
        KnowledgeGapReport(
            topic_id=topic_id,
            title="Parking",
            content="Text",
            sources=[KnowledgeGapSource(kind="question", id=question.search_id)],
        ),
    )

    detail = await KnowledgeGapService(db).read(ctx, topic_id)
    assert detail.draft is not None
    assert [(s.kind, s.label) for s in detail.draft.sources] == [("question", question.query)]


async def _called(
    db, answer: Message, tool_name: str, query: str, result: str | None, *, at: int = 0
) -> None:
    db.add(
        ToolCall(
            id=uuid.uuid4(),
            message_id=answer.id,
            tool_call_id=f"call-{uuid.uuid4().hex[:6]}",
            tool_name=tool_name,
            args={"query": query},
            result=result,
            status="completed",
            started_at=_START + timedelta(seconds=at),
        )
    )
    await db.flush()


async def _drafted_from(db, ctx: AuthContext, agent: Agent, topic_id: uuid.UUID) -> str:
    drafting_run, _ = await _turn(db, ctx, agent)
    with _drafter(KnowledgeGapDraft(title="Parking", content="Level -1."), drafting_run) as run_it:
        await KnowledgeGapService(db).draft(ctx, topic_id)
    return run_it.await_args.kwargs["prompt"]


async def _one_question_topic(db, ctx: AuthContext, kb: KnowledgeBase, agent: Agent, **turn):
    run, answer = await _turn(db, ctx, agent, question="Where do visitors park?", **turn)
    await _searched(db, ctx, run, kb, query="visitor parking")
    return run, answer


async def test_what_another_tool_returned_for_the_same_query_is_not_what_the_search_found(
    db,
) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    _, answer = await _one_question_topic(db, ctx, kb, agent)
    await _called(db, answer, "search_documents", "visitor parking", "From the handbook", at=1)
    await _called(db, answer, "web_search", "visitor parking", "From the open web", at=2)
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)

    prompt = await _drafted_from(db, ctx, agent, topic_id)

    assert "Found: From the handbook" in prompt
    assert "From the open web" not in prompt


async def test_a_knowledge_tool_its_binding_renamed_is_still_what_the_search_found(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=1,
        spec={
            "name": agent.name,
            "capabilities": [
                {
                    "id": "knowledge",
                    "tool_overrides": {"search_documents": {"name": "search_handbook"}},
                }
            ],
        },
    )
    db.add(version)
    await db.flush()
    run, answer = await _one_question_topic(db, ctx, kb, agent)
    run.agent_version_id = version.id
    await db.flush()
    await _called(db, answer, "search_handbook", "visitor parking", "From the handbook")
    await _called(db, answer, "search_documents", "visitor parking", "Not this agent's tool")
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)

    prompt = await _drafted_from(db, ctx, agent, topic_id)

    assert "Found: From the handbook" in prompt
    assert "Not this agent's tool" not in prompt


async def test_searches_with_one_query_take_its_calls_only_when_no_result_could_be_another(
    db,
) -> None:
    """Calls and searches of one turn are recorded in no order, so two searches with
    one query take a result only when every call with it returned the same text."""
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    run, answer = await _one_question_topic(db, ctx, kb, agent)
    await _searched(db, ctx, run, kb, query="visitor parking")
    await _called(db, answer, "search_documents", "visitor parking", "First result", at=1)
    await _called(db, answer, "search_documents", "visitor parking", "Second result", at=2)
    again, twice = await _turn(db, ctx, agent, question="Visitor parking at the back?")
    for _ in range(2):
        await _searched(db, ctx, again, kb, query="back parking")
        await _called(db, twice, "search_documents", "back parking", "Behind the depot")
    other, short = await _turn(db, ctx, agent, question="Is there parking at night?")
    await _searched(db, ctx, other, kb, query="night parking")
    await _searched(db, ctx, other, kb, query="night parking")
    await _called(db, short, "search_documents", "night parking", "One of two results")
    late, cut = await _turn(db, ctx, agent, question="Parking on Sundays?")
    await _searched(db, ctx, late, kb, query="sunday parking")
    await _called(db, cut, "search_documents", "sunday parking", None)
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)

    prompt = await _drafted_from(db, ctx, agent, topic_id)

    assert "First result" not in prompt and "Second result" not in prompt
    assert prompt.count("Found: Behind the depot") == 2
    assert "One of two results" not in prompt


async def test_a_question_read_from_an_answer_takes_what_its_query_found(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    run, answer = await _turn(db, ctx, agent, question="Where do visitors park?")
    db.add(
        KnowledgeSearch(
            organization_id=ctx.organization_id,
            run_id=run.id,
            agent_id=agent.id,
            conversation_id=run.conversation_id,
            knowledge_base_ids=[kb.id],
            query="Where do visitors park?",
            result_count=3,
            top_similarity=0.6,
            signal=GapSignal.ANSWER.value,
            message_id=answer.id,
        )
    )
    await db.flush()
    await _called(db, answer, "search_documents", "Where do visitors park?", "Staff car park")
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)

    prompt = await _drafted_from(db, ctx, agent, topic_id)

    assert "Found: Staff car park" in prompt
