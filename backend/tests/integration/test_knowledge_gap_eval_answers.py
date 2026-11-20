"""An improvement session's failed eval answers, sorted for missing knowledge on a real database.

A session that learns from evals has no chat answer to sort: its evidence is the
eval's answers to training questions, which have no message. The classifier stands
in for the model as in `test_knowledge_gap_causes.py`, deciding by the words in
front of it.
"""

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.eval_run import EvalRunCase
from app.db.models.knowledge_gap import KnowledgeGapEvalClassification, KnowledgeSearch
from app.repositories import personal_data_repo
from app.schemas.eval_run import EvalRunRequest
from app.schemas.knowledge_gap import ClassifiedAnswer
from app.schemas.knowledge_gap import KnowledgeGapClassification as Report
from app.services.eval_run import EvalRunService
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.system_agent_runner import SystemAgentResult
from tests.integration.test_eval_runs import Model, _agent, _dataset, _owner, _run_to_end
from tests.integration.test_eval_runs import _environment as _environment
from tests.integration.test_knowledge_gap_causes import _classifier
from tests.integration.test_knowledge_gap_signals import _ANSWER, _classifier_run, _decide
from tests.integration.test_knowledge_gaps import _embedding, _knowledge_base

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("knowledge_search")]

_SILENT = "I don't know the lead time: the documents do not state it."


async def _answered(
    db: AsyncSession, ctx: AuthContext, *, silent_on: tuple[str, ...] = ("Question 0",)
) -> tuple[Agent, dict[str, EvalRunCase]]:
    """An eval of two questions: those in `silent_on` the documents are silent on, the
    rest answered wrong."""
    agent, _ = await _agent(db, ctx)
    dataset = await _dataset(db, ctx, cases=2)
    run = await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    model = Model(
        db,
        answer=lambda prompt, call: (
            _SILENT if any(question in prompt for question in silent_on) else "It costs 10 pounds."
        ),
    )
    await _run_to_end(db, model, run.id, ctx)
    attempts = (
        await db.scalars(select(EvalRunCase).where(EvalRunCase.eval_run_id == run.id))
    ).all()
    named = {"silent" if attempt.answer == _SILENT else "wrong": attempt for attempt in attempts}
    if len(named) == len(attempts):
        return agent, named
    return agent, {f"silent {attempt.position}": attempt for attempt in attempts}


def _runs(asked: dict[str, EvalRunCase]) -> list[UUID]:
    return [run_id for attempt in asked.values() if (run_id := attempt.agent_run_id)]


async def test_a_failed_eval_answer_the_agent_did_not_know_becomes_a_gap_once(db) -> None:
    ctx = await _owner(db)
    agent, asked = await _answered(db, ctx)
    kb = await _knowledge_base(db, ctx)
    classifier = await _classifier_run(db, ctx, agent)
    service = KnowledgeGapService(db)

    with _classifier(classifier) as run_it:
        read, misses = await service.classify_batch(
            ctx, kb.id, message_ids=[], eval_run_ids=_runs(asked)
        )
        again = await service.classify_batch(ctx, kb.id, message_ids=[], eval_run_ids=_runs(asked))
    causes = await service.eval_causes(ctx, [kb.id], _runs(asked))

    assert (read, misses) == (2, 1)
    assert again == (0, 0)
    assert run_it.await_count == 1
    prompt = str(run_it.await_args.kwargs["prompt"])
    assert "Asked: Question 0" in prompt and _SILENT in prompt
    silent, wrong = asked["silent"].agent_run_id, asked["wrong"].agent_run_id
    assert silent is not None and wrong is not None
    assert causes[silent][0] == "missing_knowledge"
    assert causes[wrong][0] == "agent"
    [miss] = (
        await db.scalars(select(KnowledgeSearch).where(KnowledgeSearch.run_id == silent))
    ).all()
    assert (miss.query, miss.signal, miss.message_id, miss.conversation_id) == (
        "Question 0",
        "answer",
        None,
        None,
    )
    assert miss.knowledge_base_ids == [kb.id]


async def test_an_eval_answer_s_gap_goes_with_the_case_s_copies(db) -> None:
    """The miss holds the case's question and the verdict a model's words on its answer."""
    ctx = await _owner(db)
    agent, asked = await _answered(db, ctx)
    kb = await _knowledge_base(db, ctx)
    classifier = await _classifier_run(db, ctx, agent)
    with _classifier(classifier):
        await KnowledgeGapService(db).classify_batch(
            ctx, kb.id, message_ids=[], eval_run_ids=_runs(asked)
        )

    await personal_data_repo.purge_case_copies(db, [asked["silent"].case_revision_id])

    silent = asked["silent"].agent_run_id
    assert (
        await db.scalars(select(KnowledgeSearch).where(KnowledgeSearch.run_id == silent))
    ).all() == []
    kept = (await db.scalars(select(KnowledgeGapEvalClassification.run_id))).all()
    assert silent not in kept and asked["wrong"].agent_run_id in kept


async def test_an_answer_cleared_while_the_model_read_it_records_nothing(db) -> None:
    ctx = await _owner(db)
    agent, asked = await _answered(db, ctx)
    kb = await _knowledge_base(db, ctx)
    classifier = await _classifier_run(db, ctx, agent)

    async def classify(ctx: AuthContext, **kwargs: object) -> SystemAgentResult[Report]:
        await personal_data_repo.purge_case_copies(db, [asked["silent"].case_revision_id])
        answers = [
            ClassifiedAnswer(number=int(number), signal=_decide(block), reason="read")
            for number, block in _ANSWER.findall(str(kwargs["prompt"]))
        ]
        return SystemAgentResult(output=Report(answers=answers), run=classifier)

    with patch(
        "app.services.knowledge_gaps.SystemAgentRunner.run", new=AsyncMock(side_effect=classify)
    ):
        read, misses = await KnowledgeGapService(db).classify_batch(
            ctx, kb.id, message_ids=[], eval_run_ids=_runs(asked)
        )

    assert (read, misses) == (2, 0)
    silent = asked["silent"].agent_run_id
    kept = (await db.scalars(select(KnowledgeGapEvalClassification.run_id))).all()
    assert silent not in kept and asked["wrong"].agent_run_id in kept


async def test_misses_the_classifier_named_alike_form_one_topic_named_for_what_is_missing(
    db,
) -> None:
    """Two customers' different questions about lead times are one topic, named for
    the subject rather than for whichever question came first."""
    ctx = await _owner(db)
    agent, asked = await _answered(db, ctx, silent_on=("Question 0", "Question 1"))
    kb = await _knowledge_base(db, ctx)
    classifier = await _classifier_run(db, ctx, agent)

    async def classify(ctx: AuthContext, **kwargs: object) -> SystemAgentResult[Report]:
        answers = [
            ClassifiedAnswer(
                number=int(number), signal="did_not_know", topic=" Lead times by product "
            )
            for number, _ in _ANSWER.findall(str(kwargs["prompt"]))
        ]
        return SystemAgentResult(output=Report(answers=answers), run=classifier)

    service = KnowledgeGapService(db)
    with patch(
        "app.services.knowledge_gaps.SystemAgentRunner.run", new=AsyncMock(side_effect=classify)
    ):
        await service.classify_batch(ctx, kb.id, message_ids=[], eval_run_ids=_runs(asked))
    with _embedding() as embedder:
        await service.group_pending(organization_id=ctx.organization_id, knowledge_base_id=kb.id)
    topics = await service.list_for_knowledge_base(ctx, kb.id)

    embedder.embed_queries.assert_called_once_with(["Lead times by product"])
    [topic] = topics.items
    assert topic.label == "Lead times by product"
    assert sorted(topic.examples) == ["Question 0", "Question 1"]
    # The topic's own page names each as the test question it was, not a lost conversation.
    detail = await service.read(ctx, topic.id)
    assert sorted((q.question, q.test_question) for q in detail.questions) == [
        ("Question 0", True),
        ("Question 1", True),
    ]
