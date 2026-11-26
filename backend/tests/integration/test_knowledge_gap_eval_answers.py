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
    from app.db.models.run_manifest import RunManifest

    manifest = RunManifest(
        run_id=classifier.id,
        organization_id=ctx.organization_id,
        payload={"messages": ["erased while classifying"], "tools": []},
    )
    db.add(manifest)
    await db.flush()

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

    await db.refresh(manifest)
    assert manifest.payload == {"tools": []}
    assert manifest.truncated


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
    # Test questions came up; nobody asked them.
    assert (topic.question_count, topic.test_question_count, topic.asker_count) == (2, 2, 0)
    assert sorted(topic.examples) == ["Question 0", "Question 1"]
    # The topic's own page names each as the test question it was, not a lost conversation.
    detail = await service.read(ctx, topic.id)
    assert sorted((q.question, q.test_question) for q in detail.questions) == [
        ("Question 0", True),
        ("Question 1", True),
    ]


@pytest.mark.parametrize("purge_first", [False, True])
async def test_case_erasure_and_eval_classification_share_answer_locks(
    db, engine, purge_first
) -> None:
    """The lock must also cover a case whose question came through history or a run,
    with no asked_by_user_id for the classifier to lock."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.repositories import knowledge_gap_repo

    ctx = await _owner(db)
    _, asked = await _answered(db, ctx)
    attempt = asked["silent"]
    run_ids = _runs(asked)
    revision = attempt.case_revision_id
    await db.commit()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as other:
        await other.execute(text("SET LOCAL lock_timeout = '100ms'"))
        if purge_first:
            await personal_data_repo.purge_case_copies(db, [revision])
            with pytest.raises(DBAPIError, match="lock timeout"):
                await knowledge_gap_repo.eval_answers_kept(
                    other, run_ids, organization_id=ctx.organization_id
                )
        else:
            assert attempt.agent_run_id in await knowledge_gap_repo.eval_answers_kept(
                db, run_ids, organization_id=ctx.organization_id
            )
            with pytest.raises(DBAPIError, match="lock timeout"):
                await personal_data_repo.purge_case_copies(other, [revision])
        await other.rollback()
        await db.commit()
        await personal_data_repo.purge_case_copies(other, [revision])
        await other.commit()
        assert attempt.agent_run_id not in await knowledge_gap_repo.eval_answers_kept(
            other, run_ids, organization_id=ctx.organization_id
        )


async def test_purging_eval_copies_also_forgets_the_classifiers_manifest(db) -> None:
    from app.db.models.run_manifest import RunManifest

    ctx = await _owner(db)
    agent, asked = await _answered(db, ctx)
    kb = await _knowledge_base(db, ctx)
    classifier = await _classifier_run(db, ctx, agent)
    manifest = RunManifest(
        run_id=classifier.id,
        organization_id=ctx.organization_id,
        payload={"messages": ["private question and answer"], "tools": []},
    )
    db.add(manifest)
    await db.flush()
    with _classifier(classifier):
        await KnowledgeGapService(db).classify_batch(
            ctx, kb.id, message_ids=[], eval_run_ids=_runs(asked)
        )
    await personal_data_repo.purge_case_copies(db, [asked["silent"].case_revision_id])
    await db.refresh(manifest)
    assert manifest.payload == {"tools": []}
    assert manifest.truncated


async def test_competing_eval_verdicts_keep_the_miss_consistent_with_the_winner(db, engine) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models.knowledge_gap import GapSignal
    from app.repositories import knowledge_gap_repo
    from app.repositories.knowledge_gap import Verdict

    ctx = await _owner(db)
    agent, asked = await _answered(db, ctx)
    kb = await _knowledge_base(db, ctx)
    first = await _classifier_run(db, ctx, agent)
    second = await _classifier_run(db, ctx, agent)
    candidates = await knowledge_gap_repo.eval_answer_candidates(
        db,
        kb.id,
        organization_id=ctx.organization_id,
        run_ids=[asked["silent"].agent_run_id],
        limit=1,
    )
    candidate = candidates[0]
    await db.commit()
    gate = asyncio.Barrier(2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def write(miss: bool, classifier_id: UUID) -> tuple[int, int]:
        async with sessions() as session:
            await gate.wait()
            result = await knowledge_gap_repo.record_eval_classifications(
                session,
                [
                    Verdict(
                        candidate=candidate,
                        verdict="answer" if miss else "none",
                        signal=GapSignal.ANSWER if miss else None,
                        query="Lead times",
                    )
                ],
                kb.id,
                organization_id=ctx.organization_id,
                run_id=classifier_id,
            )
            await session.commit()
            return result

    async with asyncio.timeout(5):
        results = await asyncio.gather(write(True, first.id), write(False, second.id))
    assert sum(count for count, _ in results) == 1
    verdict = await db.scalar(
        select(KnowledgeGapEvalClassification).where(
            KnowledgeGapEvalClassification.run_id == candidate.run_id
        )
    )
    assert verdict is not None
    misses = (
        await db.scalars(select(KnowledgeSearch).where(KnowledgeSearch.run_id == candidate.run_id))
    ).all()
    assert bool(misses) == (verdict.signal == "answer")
