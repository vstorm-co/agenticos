"""Knowledge gaps read from answers and thumbs-down comments, against a real database.

A model reads a knowledge base's recent answers for the ones in which the agent
did not know, and the comments that say what was missing. These tests stand in
for the model with one that decides by the words in front of it, and pin what
it is shown - only the organization's own people's answers, never an eval's -
what is remembered, and who may ask for it at all.
"""

import dataclasses
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.audit import set_impersonator
from app.core.exceptions import AiAssistanceDisabledError, AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation, Message
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.knowledge_gap import KnowledgeGapClassification, KnowledgeSearch
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization
from app.schemas.knowledge_gap import ClassifiedAnswer
from app.schemas.knowledge_gap import KnowledgeGapClassification as Report
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.personal_data import PersonalDataService
from app.services.system_agent_runner import SystemAgentResult
from tests.integration.test_knowledge_gaps import (
    _agent,
    _embedding,
    _knowledge_base,
    _member,
    _owner,
    _searched,
    _topics,
    _user,
)

pytestmark = pytest.mark.anyio

_ANSWER = re.compile(r"## Answer (\d+)\n(.*?)(?=\n## Answer |\Z)", re.S)


def _decide(block: str) -> Literal["answer", "rating", "none"]:
    """What a careful model would say about one numbered answer."""
    if "don't know" in block or "nie wiem" in block:
        return "answer"
    if "missing" in block:
        return "rating"
    return "none"


@contextmanager
def _classifier(run: AgentRun, *, drop: int = 0) -> Iterator[AsyncMock]:
    """A classifier deciding by the words it is shown, that may leave the last answers out."""

    async def classify(ctx: AuthContext, **kwargs: object) -> SystemAgentResult[Report]:
        blocks = _ANSWER.findall(str(kwargs["prompt"]))
        answers = [
            ClassifiedAnswer(number=int(number), signal=_decide(block))
            for number, block in blocks[: len(blocks) - drop]
        ]
        return SystemAgentResult(output=Report(answers=answers), run=run)

    run_it = AsyncMock(side_effect=classify)
    with patch("app.services.knowledge_gaps.SystemAgentRunner.run", new=run_it):
        yield run_it


async def _asked(
    db,
    ctx: AuthContext,
    agent: Agent,
    *,
    question: str,
    answer: str,
    surface: str = "web",
    is_test: bool = False,
    parent: AgentRun | None = None,
    version: AgentVersion | None = None,
) -> tuple[AgentRun, Message]:
    """A person's question in a conversation of their own, and the agent's answer."""
    conversation = Conversation(
        id=uuid.uuid4(), user_id=ctx.user_id, organization_id=ctx.organization_id, title="Q"
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
        surface=surface,
        is_test=is_test,
        parent_run_id=None if parent is None else parent.id,
        agent_version_id=None if version is None else version.id,
        started_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(run)
    await db.flush()
    reply = None
    for role, content in (("user", question), ("assistant", answer)):
        reply = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            run_id=run.id,
            role=role,
            content=content,
        )
        db.add(reply)
        await db.flush()
    assert reply is not None
    return run, reply


async def _rated_down(db, message: Message, user_id: uuid.UUID, comment: str) -> MessageRating:
    rating = MessageRating(message_id=message.id, user_id=user_id, rating=-1, comment=comment)
    db.add(rating)
    await db.flush()
    return rating


async def _binding(db, ctx: AuthContext, agent: Agent, kb: KnowledgeBase) -> AgentVersion:
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=1,
        spec={"collection_ids": [str(kb.id)]},
    )
    db.add(version)
    await db.flush()
    return version


async def _classifier_run(db, ctx: AuthContext, agent: Agent) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        status="completed",
        surface="eval",
        cost_usd=0.0012,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return run


async def _check(db, ctx: AuthContext, kb: KnowledgeBase, run: AgentRun, **kwargs) -> tuple:
    with _classifier(run, **kwargs) as run_it:
        read = await KnowledgeGapService(db).classify_batch(ctx, kb.id)
    return read, run_it


async def _signals(db, kb: KnowledgeBase) -> dict[str, str]:
    rows = await db.execute(
        select(KnowledgeSearch.query, KnowledgeSearch.signal).where(
            KnowledgeSearch.signal != "retrieval",
            KnowledgeSearch.knowledge_base_ids.any(kb.id),
        )
    )
    return dict(rows.tuples().all())


async def test_an_answer_in_which_the_agent_did_not_know_becomes_a_grouped_miss(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    unknown, _ = await _asked(
        db, ctx, agent, question="Is there parking for visitors?", answer="I don't know."
    )
    known, _ = await _asked(
        db, ctx, agent, question="When is the office open?", answer="From 8 to 18."
    )
    await _searched(db, ctx, unknown, kb, query="visitor parking", top_similarity=0.9)
    await _searched(db, ctx, known, kb, query="office hours", top_similarity=0.9)
    classifier = await _classifier_run(db, ctx, agent)

    (read, misses), run_it = await _check(db, ctx, kb, classifier)
    with _embedding():
        await KnowledgeGapService(db).group_pending(
            organization_id=ctx.organization_id, knowledge_base_id=kb.id
        )

    assert (read, misses) == (2, 1)
    assert run_it.await_args.kwargs["key"] == "knowledge_gap_classifier"
    assert await _signals(db, kb) == {"Is there parking for visitors?": "answer"}
    assert list((await _topics(db, kb)).values()) == [["Is there parking for visitors?"]]
    topic = (await KnowledgeGapService(db).list_for_knowledge_base(ctx, kb.id)).items[0]
    [question] = (await KnowledgeGapService(db).read(ctx, topic.id)).questions
    assert (question.signal, question.result_count, question.top_similarity) == ("answer", 3, 0.9)
    remembered = await db.execute(
        select(KnowledgeGapClassification.signal, KnowledgeGapClassification.run_id)
    )
    assert sorted(remembered.tuples().all()) == [
        ("answer", classifier.id),
        ("none", classifier.id),
    ]


async def test_a_comment_naming_missing_information_is_a_miss_and_one_about_length_is_not(
    db,
) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    version = await _binding(db, ctx, agent, kb)
    _, missing = await _asked(
        db, ctx, agent, question="What does the plan cost?", answer="It costs 10.", version=version
    )
    _, long = await _asked(
        db, ctx, agent, question="What is the plan?", answer="A long answer.", version=version
    )
    _, unrated = await _asked(
        db, ctx, agent, question="Who runs the plan?", answer="Ann.", version=version
    )
    await _rated_down(db, missing, ctx.user_id, "This is missing the 2025 price list")
    await _rated_down(db, long, ctx.user_id, "Too long")
    classifier = await _classifier_run(db, ctx, agent)

    (read, misses), run_it = await _check(db, ctx, kb, classifier)

    assert (read, misses) == (2, 1)
    assert await _signals(db, kb) == {"What does the plan cost?": "rating"}
    prompt = run_it.await_args.kwargs["prompt"]
    assert "This is missing the 2025 price list" in prompt
    assert "Who runs the plan?" not in prompt


@pytest.mark.security
async def test_a_miss_read_from_an_answer_belongs_to_the_knowledge_base_checked_alone(
    db,
) -> None:
    """The check rested on the caller's access to one knowledge base, so what it
    finds is that base's; another base the run searched reads the answer for itself."""
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    handbook = await _knowledge_base(db, ctx, "policies")
    agent = await _agent(db, ctx)
    run, _ = await _asked(db, ctx, agent, question="Visitor parking?", answer="I don't know.")
    await _searched(db, ctx, run, kb, query="parking", top_similarity=0.7)
    await _searched(db, ctx, run, kb, query="visitor parking", top_similarity=0.9)
    await _searched(db, ctx, run, kb, query="garage", top_similarity=None)
    await _searched(db, ctx, run, handbook, query="parking rules", top_similarity=0.95)
    await db.execute(
        KnowledgeSearch.__table__.update()
        .where(KnowledgeSearch.query == "garage")
        .values(result_count=2)
    )
    classifier = await _classifier_run(db, ctx, agent)
    service = KnowledgeGapService(db)

    first, _ = await _check(db, ctx, kb, classifier)
    waiting = (await service.list_for_knowledge_base(ctx, handbook.id)).unchecked
    second, _ = await _check(db, ctx, handbook, classifier)

    rows = (
        (await db.execute(select(KnowledgeSearch).where(KnowledgeSearch.signal == "answer")))
        .scalars()
        .all()
    )
    assert (first, waiting, second) == ((1, 1), 1, (1, 1))
    assert sorted((r.knowledge_base_ids, r.top_similarity) for r in rows) == sorted(
        [([kb.id], 0.9), ([handbook.id], 0.95)]
    )
    assert {r.result_count for r in rows if r.knowledge_base_ids == [kb.id]} == {3}


@pytest.mark.security
async def test_an_answer_whose_asker_is_erased_during_the_check_leaves_no_miss(db) -> None:
    """The model call takes time; an erasure that lands in it has removed the
    person's searches already, and a miss recorded afterwards would outlive them."""
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    asker = await _member(db, ctx, OrgRoleName.MEMBER)
    run, _ = await _asked(db, asker, agent, question="Parking?", answer="I don't know.")
    await _searched(db, ctx, run, kb, query="parking", top_similarity=0.9)
    classifier = await _classifier_run(db, ctx, agent)
    run_id = run.id

    async def erased_meanwhile(_ctx: AuthContext, **kwargs: object) -> SystemAgentResult[Report]:
        await db.execute(
            AgentRun.__table__.update().where(AgentRun.id == run_id).values(user_id=None)
        )
        return SystemAgentResult(
            output=Report(answers=[ClassifiedAnswer(number=1, signal="answer")]), run=classifier
        )

    with patch(
        "app.services.knowledge_gaps.SystemAgentRunner.run",
        new=AsyncMock(side_effect=erased_meanwhile),
    ):
        read = await KnowledgeGapService(db).classify_batch(ctx, kb.id)

    assert read == (1, 0)
    assert await _signals(db, kb) == {}
    assert (await KnowledgeGapService(db).list_for_knowledge_base(ctx, kb.id)).unchecked == 0


async def test_only_the_newest_comments_on_an_answer_are_shown(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    run, answer = await _asked(db, ctx, agent, question="Price?", answer="It is 10.")
    await _searched(db, ctx, run, kb, query="price", top_similarity=0.9)
    for n in range(7):
        rating = await _rated_down(db, answer, (await _user(db)).id, f"comment {n}")
        rated_at = datetime.now(UTC) - timedelta(minutes=10 - n)
        await db.execute(
            MessageRating.__table__.update()
            .where(MessageRating.id == rating.id)
            .values(created_at=rated_at, updated_at=rated_at)
        )

    _, run_it = await _check(db, ctx, kb, await _classifier_run(db, ctx, agent))

    prompt = run_it.await_args.kwargs["prompt"]
    assert [n for n in range(7) if f"comment {n}" in prompt] == [2, 3, 4, 5, 6]


async def test_a_run_whose_search_missed_is_already_counted_and_is_not_read(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    run, _ = await _asked(db, ctx, agent, question="Where is it?", answer="I don't know.")
    await _searched(db, ctx, run, kb, query="where", top_similarity=0.1)

    with patch("app.services.knowledge_gaps.SystemAgentRunner.run", new=AsyncMock()) as run_it:
        read = await KnowledgeGapService(db).classify_batch(ctx, kb.id)

    assert read == (0, 0)
    run_it.assert_not_awaited()


@pytest.mark.security
async def test_evals_tests_delegates_and_other_organizations_are_never_read(db) -> None:
    """An eval replays or generates its questions, so reading its answers would feed
    a dataset back into itself, and a builder testing a draft is not asking; another
    organization's answers are not ours to read."""
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    ours, _ = await _asked(db, ctx, agent, question="ours", answer="I don't know.")
    replayed, _ = await _asked(
        db, ctx, agent, question="replayed", answer="I don't know.", surface="eval"
    )
    delegated, _ = await _asked(
        db, ctx, agent, question="delegated", answer="I don't know.", parent=ours
    )
    tested, _ = await _asked(
        db, ctx, agent, question="tested", answer="I don't know.", is_test=True
    )
    parked, _ = await _asked(db, ctx, agent, question="parked", answer="I don't know.")
    parked.status = "awaiting_approval"
    other = await _owner(db)
    foreign, _ = await _asked(
        db, other, await _agent(db, other), question="foreign", answer="I don't know."
    )
    for run in (ours, replayed, delegated, tested, parked, foreign):
        await _searched(
            db, ctx if run is not foreign else other, run, kb, query="q", top_similarity=0.9
        )
    classifier = await _classifier_run(db, ctx, agent)

    (read, _), run_it = await _check(db, ctx, kb, classifier)

    prompt = run_it.await_args.kwargs["prompt"]
    assert read == 1
    assert "ours" in prompt
    assert not {"replayed", "delegated", "tested", "parked", "foreign"} & set(
        re.findall(r"Asked: (\w+)", prompt)
    )
    with pytest.raises(NotFoundError):
        await KnowledgeGapService(db).classify(other, kb.id)


async def test_an_answer_read_once_waits_for_a_new_thumbs_down_before_it_is_read_again(
    db,
) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    run, answer = await _asked(db, ctx, agent, question="Price?", answer="It is 10.")
    await _searched(db, ctx, run, kb, query="price", top_similarity=0.9)
    classifier = await _classifier_run(db, ctx, agent)
    service = KnowledgeGapService(db)

    first, _ = await _check(db, ctx, kb, classifier)
    with patch("app.services.knowledge_gaps.SystemAgentRunner.run", new=AsyncMock()) as idle:
        again = await service.classify_batch(ctx, kb.id)
    await db.execute(
        KnowledgeGapClassification.__table__.update().values(
            classified_at=datetime.now(UTC) - timedelta(minutes=5)
        )
    )
    await _rated_down(db, answer, ctx.user_id, "The 2025 price is missing")
    unchecked = (await service.list_for_knowledge_base(ctx, kb.id)).unchecked
    second, _ = await _check(db, ctx, kb, classifier)

    assert (first, again) == ((1, 0), (0, 0))
    idle.assert_not_awaited()
    assert unchecked == 1
    assert second == (1, 1)
    assert await _signals(db, kb) == {"Price?": "rating"}


async def test_a_number_naming_no_answer_is_dropped_and_a_skipped_answer_waits(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    for n in range(2):
        run, _ = await _asked(db, ctx, agent, question=f"q{n}", answer="I don't know.")
        await _searched(db, ctx, run, kb, query=f"q{n}", top_similarity=0.9)
    classifier = await _classifier_run(db, ctx, agent)
    report = Report(
        answers=[
            ClassifiedAnswer(number=1, signal="answer"),
            ClassifiedAnswer(number=1, signal="none"),
            ClassifiedAnswer(number=7, signal="answer"),
        ]
    )

    with patch(
        "app.services.knowledge_gaps.SystemAgentRunner.run",
        new=AsyncMock(return_value=SystemAgentResult(output=report, run=classifier)),
    ):
        read = await KnowledgeGapService(db).classify_batch(ctx, kb.id)

    assert read == (1, 1)
    assert (await KnowledgeGapService(db).list_for_knowledge_base(ctx, kb.id)).unchecked == 1


async def test_a_miss_read_from_an_answer_is_in_its_askers_export(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    run, _ = await _asked(db, ctx, agent, question="Visitor parking?", answer="I don't know.")
    await _searched(db, ctx, run, kb, query="visitor parking", top_similarity=0.9)

    await _check(db, ctx, kb, await _classifier_run(db, ctx, agent))
    export = await PersonalDataService(db).export(ctx.user_id, actor_user_id=ctx.user_id)

    assert sorted(row["query"] for row in export.knowledge_searches) == [
        "Visitor parking?",
        "visitor parking",
    ]


async def test_checking_answers_starts_after_the_commit_as_the_caller(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)

    with (
        patch("app.services.knowledge_gaps.SystemAgentRunner.require_runnable", new=AsyncMock()),
        patch("app.services.knowledge_gaps.spawn_after_commit") as spawn,
    ):
        await KnowledgeGapService(db).classify(ctx, kb.id)

    assert spawn.call_args.kwargs["name"] == f"classify-knowledge-gaps-{kb.id}"
    spawn.call_args.args[1].close()


@pytest.mark.security
async def test_with_ai_assistance_off_no_check_starts(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    organization = await db.get(Organization, ctx.organization_id)
    assert organization is not None
    organization.ai_assistance_enabled = False
    await db.flush()

    with (
        patch("app.services.knowledge_gaps.spawn_after_commit") as spawn,
        pytest.raises(AiAssistanceDisabledError),
    ):
        await KnowledgeGapService(db).classify(ctx, kb.id)

    spawn.assert_not_called()


@pytest.mark.security
async def test_only_whoever_may_change_the_knowledge_base_and_reads_every_run_may_check(
    db,
) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)
    member = await _member(db, ctx, OrgRoleName.MEMBER)
    service = KnowledgeGapService(db)

    with patch("app.services.knowledge_gaps.spawn_after_commit") as spawn:
        with pytest.raises(NotFoundError):
            await service.classify(operator, kb.id)
        with pytest.raises(NotFoundError):
            await service.classify_batch(operator, kb.id)
        with pytest.raises(AuthorizationError):
            await service.classify(member, kb.id)

    spawn.assert_not_called()


@pytest.mark.security
async def test_a_check_is_started_only_in_person(db) -> None:
    """It runs later on the caller's role, so neither an API key's narrower scopes
    nor an administrator acting as somebody else may start one."""
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    keyed = dataclasses.replace(ctx, api_key_id=uuid.uuid4())

    with patch("app.services.knowledge_gaps.spawn_after_commit") as spawn:
        with pytest.raises(AuthorizationError):
            await KnowledgeGapService(db).classify(keyed, kb.id)
        set_impersonator(uuid.uuid4())
        try:
            with pytest.raises(AuthorizationError):
                await KnowledgeGapService(db).classify(ctx, kb.id)
        finally:
            set_impersonator(None)

    spawn.assert_not_called()


async def test_a_check_runs_as_its_asker_only_while_they_are_a_member(db) -> None:
    ctx = await _owner(db)
    stranger = await _user(db)
    service = KnowledgeGapService(db)

    acting = await service.acting_as(organization_id=ctx.organization_id, user_id=ctx.user_id)
    gone = await service.acting_as(organization_id=ctx.organization_id, user_id=stranger.id)

    assert acting is not None and (acting.user_id, acting.role) == (ctx.user_id, "owner")
    assert gone is None
