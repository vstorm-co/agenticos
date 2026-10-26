"""A session reads pinned, still-readable evidence without another model call."""

from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import Perm
from app.db.models.conversation import Message
from app.db.models.knowledge_gap import KnowledgeGapClassification
from app.repositories import knowledge_gap_repo
from app.services.improvement_pipeline import ImprovementPipelineService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _rated
from tests.integration.test_improvement_pipeline import _started
from tests.integration.test_knowledge_gaps import _knowledge_base

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


@pytest.fixture(autouse=True)
def _serial_worker():
    def dropped(_db, coro, *, name):
        coro.close()

    with (
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
        patch("app.services.notifications.spawn_after_commit", side_effect=dropped),
        patch("app.services.eval_suite.spawn_after_commit", side_effect=dropped),
    ):
        yield


async def test_evidence_uses_frozen_sources_and_redacts_credentials_in_every_text_field(db):
    ctx, agent, dataset, session = await _started(db)
    service = ImprovementPipelineService(db)
    original = await service.evidence(ctx, agent.id, run_id=session.id)
    assert len(original.items) == 1 and original.items[0].branch == "unknown"
    item = original.items[0]
    late = await _rated(db, ctx, agent, comment="A later problem")
    assert late.id not in {
        item.run_id for item in (await service.evidence(ctx, agent.id, run_id=session.id)).items
    }
    secret = "ghp_" + "k" * 36
    answer = await db.scalar(
        select(Message).where(Message.run_id == item.run_id, Message.role == "assistant")
    )
    answer.content = f"Your credential: {secret}"
    await db.flush()
    preview = await service.evidence(ctx, agent.id, dataset_id=dataset.id)
    assert len(preview.items) == 2
    assert secret not in preview.model_dump_json()
    assert "[redacted:" in preview.model_dump_json()
    with pytest.raises(NotFoundError):
        await service.evidence(ctx, agent.id, run_id=uuid4())
    no_runs = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.DATASETS_RUN}))
    with pytest.raises(AuthorizationError, match="runs:view"):
        await service.evidence(no_runs, agent.id, run_id=session.id)
    from tests.integration.test_authoring import _owner

    outsider = await _owner(db)
    with pytest.raises(NotFoundError):
        await service.evidence(outsider, agent.id, run_id=session.id)
    assert (
        await knowledge_gap_repo.answers_for_runs(
            db, organization_id=outsider.organization_id, run_ids=[item.run_id]
        )
        == {}
    )
    assert (
        await knowledge_gap_repo.answers_for_runs(
            db, organization_id=ctx.organization_id, run_ids=[]
        )
        == {}
    )


@pytest.mark.parametrize(
    "signal,branch",
    [("answer", "missing_knowledge"), ("refused", "not_a_problem"), ("none", "agent")],
)
async def test_recorded_causes_are_shown_only_for_current_readable_bases(db, signal, branch):
    ctx, agent, _, session = await _started(db)
    kb = await _knowledge_base(db, ctx)
    agent.draft_spec = {**agent.draft_spec, "collection_ids": [str(kb.id)]}
    evidence = await ImprovementPipelineService(db).evidence(ctx, agent.id, run_id=session.id)
    message = await db.scalar(
        select(Message).where(
            Message.run_id == evidence.items[0].run_id, Message.role == "assistant"
        )
    )
    db.add(
        KnowledgeGapClassification(
            message_id=message.id,
            knowledge_base_id=kb.id,
            organization_id=ctx.organization_id,
            signal=signal,
            reason="Verified from the source",
        )
    )
    await db.flush()
    service = ImprovementPipelineService(db)
    item = (await service.evidence(ctx, agent.id, run_id=session.id)).items[0]
    assert item.branch == branch and item.reason == "Verified from the source"
    limited = replace(
        ctx,
        key_scopes=frozenset(
            {Perm.AGENTS_VIEW, Perm.RUNS_VIEW, Perm.DATASETS_RUN, Perm.DATASETS_VIEW}
        ),
    )
    hidden = (await service.evidence(limited, agent.id, run_id=session.id)).items[0]
    assert hidden.branch == "unknown" and hidden.reason is None


async def test_training_preview_preserves_the_run_reader_boundary(db):
    from app.core.permissions import OrgRoleName
    from app.db.models.dataset import Dataset, DatasetCase
    from app.schemas.dataset import DatasetCaseFromMessage, DatasetCaseUpdate, DatasetCreate
    from app.services.authoring_evidence import EvidenceService
    from app.services.dataset import DatasetService
    from app.services.eval_suite import EvalSuiteService
    from tests.integration.test_datasets import _rated_down_turn
    from tests.integration.test_eval_suites import (
        Model,
        _agent,
        _finish_runs,
        _member,
        _owner,
        _suite_data,
    )

    owner = await _owner(db)
    curator = await _member(db, owner, OrgRoleName.OWNER)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="private training example"))
    _, answer = await _rated_down_turn(db, owner)
    case = await service.add_from_message(
        owner, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
    )
    await service.update_case(
        owner,
        dataset.id,
        case.case_id,
        DatasetCaseUpdate(checks=[{"type": "contains", "value": "30 days"}]),
    )
    rows = list(await db.scalars(select(DatasetCase).where(DatasetCase.case_id == case.case_id)))
    for row in rows:
        row.improvement_partition = "train"
    agent, _ = await _agent(db, owner)
    stored = await db.get(Dataset, dataset.id)
    suite = await EvalSuiteService(db).create(owner, agent.id, _suite_data(stored))
    await EvalSuiteService(db).run_now(owner, agent.id, suite.id)
    await _finish_runs(db, Model(db, answer=lambda _: "90 days"))
    own, _ = await EvidenceService(db)._train(
        owner, agent.id, window_days=30, dataset_id=dataset.id
    )
    assert len(own) == 1 and own[0].prompt == case.input
    preview = await ImprovementPipelineService(db).evidence(
        curator, agent.id, dataset_id=dataset.id
    )
    assert preview.training_failures == 1 and preview.items[0].question == case.input
    limited = replace(
        curator, key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.DATASETS_RUN, Perm.DATASETS_VIEW})
    )
    with pytest.raises(AuthorizationError, match="runs:view"):
        await ImprovementPipelineService(db).evidence(limited, agent.id, dataset_id=dataset.id)


async def test_ignoring_an_example_is_refused_outside_its_open_session(db):
    from app.core.exceptions import BadRequestError
    from app.core.permissions import OrgRoleName
    from app.db.models.improvement import ImprovementRun
    from app.schemas.improvement import EvidenceDecisionUpdate
    from tests.integration.test_eval_suites import _member

    ctx, agent, _, session = await _started(db)
    service = ImprovementPipelineService(db)
    [item] = (await service.evidence(ctx, agent.id, run_id=session.id)).items
    ignore = EvidenceDecisionUpdate(decision="ignored")
    ignored = await service.decide_evidence(ctx, agent.id, session.id, item.run_id, ignore)
    assert ignored.items[0].decision == "ignored" and ignored.items[0].branch == "unknown"
    preview = await service.evidence(ctx, agent.id, dataset_id=session.dataset_id)
    assert preview.items[0].decision is None and preview.items[0].branch == "unknown"
    with pytest.raises(NotFoundError, match="not one of the session's examples"):
        await service.decide_evidence(ctx, agent.id, session.id, uuid4(), ignore)
    viewer = await _member(db, ctx, OrgRoleName.VIEWER)
    with pytest.raises(NotFoundError):
        await service.decide_evidence(viewer, agent.id, session.id, item.run_id, ignore)
    no_runs = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.AGENTS_EDIT}))
    with pytest.raises(AuthorizationError):
        await service.decide_evidence(no_runs, agent.id, session.id, item.run_id, ignore)
    stored = await db.get(ImprovementRun, session.id)
    stored.status = "published"
    await db.flush()
    with pytest.raises(BadRequestError, match="decided"):
        await service.decide_evidence(ctx, agent.id, session.id, item.run_id, ignore)


async def test_a_column_a_person_chose_before_columns_became_the_classifiers_is_no_decision(db):
    from app.db.models.improvement import ImprovementRun

    ctx, agent, _, session = await _started(db)
    service = ImprovementPipelineService(db)
    [item] = (await service.evidence(ctx, agent.id, run_id=session.id)).items
    stored = await db.get(ImprovementRun, session.id)
    stored.evidence_decisions = {str(item.run_id): "missing_knowledge"}
    await db.flush()
    [read] = (await service.evidence(ctx, agent.id, run_id=session.id)).items
    assert read.decision is None and read.branch == "unknown"
    assert await service._knowledge_exclusions(ctx, stored) == []


async def test_a_knowledge_document_set_aside_stays_aside_for_the_session(db):
    from app.db.models.knowledge_gap import KnowledgeGapTopic
    from app.schemas.improvement import TopicDeferral

    ctx, agent, _, session = await _started(db)
    kb = await _knowledge_base(db, ctx)
    topic = KnowledgeGapTopic(
        organization_id=ctx.organization_id,
        knowledge_base_id=kb.id,
        centroid=[0.1],
        embedding_model="m",
    )
    db.add(topic)
    await db.flush()
    service = ImprovementPipelineService(db)
    later = await service.defer_topic(
        ctx, agent.id, session.id, topic.id, TopicDeferral(later=True)
    )
    again = await service.defer_topic(
        ctx, agent.id, session.id, topic.id, TopicDeferral(later=True)
    )
    assert later.deferred_topic_ids == again.deferred_topic_ids == [topic.id]
    back = await service.defer_topic(
        ctx, agent.id, session.id, topic.id, TopicDeferral(later=False)
    )
    assert back.deferred_topic_ids == []
    with pytest.raises(NotFoundError, match="topic not found"):
        await service.defer_topic(ctx, agent.id, session.id, uuid4(), TopicDeferral(later=True))
