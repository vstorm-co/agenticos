"""Grouping knowledge-base misses into topics, and reading answers for more of them.

Agents record their knowledge searches as they run; turning the misses into
topics needs their queries embedded, which is a network call per knowledge base
and has no place on an agent's run. A knowledge base with nothing new waiting
is not visited, so an idle deployment pays one query a pass and no embedding.

Reading answers for the questions a knowledge base could not answer asks a
model, so it runs only when a person asks for it, as them.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import SpendLedger, metered_by
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.locks import LockScope, try_hold_subject_on_connection
from app.db.models.improvement import ImprovementStage, ImprovementStatus, StopReason
from app.db.session import get_worker_connection, get_worker_db_context
from app.repositories import improvement_repo, ingestion_spend_repo
from app.services import change_feed
from app.services import improvement_states as rules
from app.services.api_key import job_context
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.knowledge_gaps import (
    CLASSIFY_BATCH,
    CLASSIFY_PER_REQUEST,
    DRAFTS_PER_ROUND,
    KnowledgeGapService,
)
from app.worker.jobs import ClassifyGaps, DraftGaps

logger = logging.getLogger(__name__)


async def group_knowledge_gaps(
    organization_id: str | None = None, knowledge_base_id: str | None = None
) -> int:
    """Group the waiting misses of every knowledge base, or of the one named with its organization.

    Each knowledge base is grouped in a transaction of its own, so one whose
    embedding provider refuses does not undo the others.

    Returns:
        How many misses were placed in a topic.
    """
    # So a Knowledge gaps tab left open hears about the questions placed.
    await change_feed.connect_in_worker()
    async with get_worker_db_context() as db:
        service = KnowledgeGapService(db)
        await service.forget_empty_topics()
        if organization_id is not None and knowledge_base_id is not None:
            waiting = [(UUID(organization_id), UUID(knowledge_base_id))]
        else:
            waiting = await service.waiting_to_be_grouped()

    grouped = 0
    for org_id, kb_id in waiting:
        try:
            async with get_worker_db_context() as db:
                placed = await KnowledgeGapService(db).group_pending(
                    organization_id=org_id, knowledge_base_id=kb_id
                )
        except Exception:
            logger.exception(
                "knowledge_gaps_grouping_failed", extra={"knowledge_base_id": str(kb_id)}
            )
            continue
        grouped += placed
        if placed:
            await change_feed.publish_knowledge_gaps_grouped(org_id)
    if grouped:
        logger.info("Knowledge gaps: %d question(s) grouped", grouped)
    return grouped


async def classify_knowledge_gaps(job: ClassifyGaps) -> int:
    """Read answers for the knowledge gaps of the job's knowledge bases, as the person who asked.

    Without `message_ids`, each knowledge base's newest unread answers, one check
    of a knowledge base at a time: a second one asked for meanwhile finds it
    held and does nothing, since the first reads the same answers. With them,
    those answers alone, as an improvement session sorts the ones it found bad;
    a session's answers are its own, so it does not wait on a check.

    Each run's verdicts commit on their own, so a check a budget stops keeps
    what it read. It stops at the first run that ends without an answer, and
    at one that reads fewer answers than it was given, rather than paying to
    read the same ones again - at most :data:`CLASSIFY_PER_REQUEST` answers a
    knowledge base.

    Returns:
        How many misses were recorded.
    """
    if job.improvement_run_id is not None:
        try:
            return await _classify_session(job)
        finally:
            await _wake_session(job)
    await change_feed.connect_in_worker()
    misses = 0
    for kb_id in job.knowledge_base_ids:
        if job.message_ids is not None:
            misses += await _classify(job, kb_id)
            continue
        async with get_worker_connection() as connection:
            held = await try_hold_subject_on_connection(
                connection, LockScope.KNOWLEDGE_GAP_CHECKS_PER_KNOWLEDGE_BASE, kb_id
            )
            if not held:
                logger.info("knowledge_gaps_check_running", extra={"knowledge_base_id": str(kb_id)})
                continue
            misses += await _classify(job, kb_id)
    return misses


async def _classify(job: ClassifyGaps, kb_id: UUID) -> int:
    read_any, misses = False, 0
    for _ in range(CLASSIFY_PER_REQUEST // CLASSIFY_BATCH):
        try:
            async with get_worker_db_context() as db:
                service = KnowledgeGapService(db)
                ctx = await service.acting_as(
                    organization_id=job.organization_id, user_id=job.user_id
                )
                if ctx is None:
                    break
                read, found = await service.classify_batch(ctx, kb_id, message_ids=job.message_ids)
        except Exception:
            logger.exception(
                "knowledge_gaps_check_stopped", extra={"knowledge_base_id": str(kb_id)}
            )
            break
        read_any, misses = read_any or read > 0, misses + found
        if read < CLASSIFY_BATCH:
            break
    if misses:
        try:
            async with get_worker_db_context() as db:
                await KnowledgeGapService(db).group_pending(
                    organization_id=job.organization_id, knowledge_base_id=kb_id
                )
        except Exception:
            # The misses are committed and the next scheduled pass groups them.
            logger.exception(
                "knowledge_gaps_grouping_failed", extra={"knowledge_base_id": str(kb_id)}
            )
    if read_any:
        await change_feed.publish_knowledge_gaps_grouped(job.organization_id)
    return misses


async def draft_knowledge_gaps(job: DraftGaps) -> int:
    """Draft the missing knowledge of an improvement session's answers, as the person it acts for.

    The answers' misses are grouped first, rather than waiting for the next
    pass, and then at most :data:`DRAFTS_PER_ROUND` of the open topics they
    joined are drafted, the most asked first, each in a run of its own. A topic
    with a draft newer than its last question is left as it is, and so is one
    too few different people asked about: one person's questions alone never
    decide what everybody is told. So is one whose content a person saved
    meanwhile, and one gone since the round listed it. Nothing is grouped for a
    person no longer a member. Any other refusal - a spent budget, AI assistance
    switched off - ends the job, and what it drafted stays.

    Returns:
        How many topics were drafted.
    """
    if job.improvement_run_id is not None:
        try:
            return await _draft_session(job)
        finally:
            await _wake_session(job)
    async with get_worker_db_context() as db:
        ctx = await KnowledgeGapService(db).acting_as(
            organization_id=job.organization_id, user_id=job.user_id
        )
    if ctx is None:
        return 0
    for kb_id in job.knowledge_base_ids:
        async with get_worker_db_context() as db:
            await KnowledgeGapService(db).group_pending(
                organization_id=job.organization_id, knowledge_base_id=kb_id
            )
    async with get_worker_db_context() as db:
        topics = await KnowledgeGapService(db).topics_to_draft(
            ctx, job.knowledge_base_ids, job.message_ids
        )
    drafted = 0
    for topic_id in topics:
        if drafted == DRAFTS_PER_ROUND:
            break
        try:
            async with get_worker_db_context() as db:
                await KnowledgeGapService(db).draft(ctx, topic_id, automatic=True)
        except NotFoundError:
            # Merged into another topic, or forgotten, since the round listed it.
            continue
        except BadRequestError as refused:
            if not {"askers", "draft_author"} & set(refused.details or {}):
                raise
            continue
        drafted += 1
    return drafted


# The queue records a job's end only after its handler returns; the session's
# advance is queued this far out so it reads that end.
_JOB_ENDS_WITHIN = timedelta(seconds=3)


async def _wake_session(job: ClassifyGaps | DraftGaps) -> None:
    assert job.improvement_run_id is not None
    async with get_worker_db_context() as db:
        await ImprovementPipelineService(db).wake(
            job.improvement_run_id, organization_id=job.organization_id, after=_JOB_ENDS_WITHIN
        )


@dataclass(frozen=True)
class _SessionSources:
    ctx: AuthContext
    knowledge_base_ids: list[UUID]
    message_ids: list[UUID]
    run_ids: list[UUID]


async def _session_sources(
    db: AsyncSession, job: ClassifyGaps | DraftGaps, stage: ImprovementStage
) -> _SessionSources:
    assert job.improvement_run_id is not None
    run = await improvement_repo.get_run(
        db, job.improvement_run_id, organization_id=job.organization_id
    )
    if run is None or run.stage != stage:
        raise BadRequestError(message="The improvement knowledge step is no longer current")
    ctx = await job_context(
        db,
        organization_id=job.organization_id,
        user_id=run.created_by_user_id,
        api_key_id=run.created_by_api_key_id,
    )
    if ctx is None:
        raise AuthorizationError(message="The improvement requester is no longer a member")
    ids, messages, runs = await ImprovementPipelineService(db).knowledge_sources(ctx, run)
    # Payloads name a snapshot, never additional authority or new evidence.
    return _SessionSources(
        ctx,
        [kb_id for kb_id in ids if kb_id in job.knowledge_base_ids],
        [message_id for message_id in messages if message_id in (job.message_ids or [])],
        runs,
    )


async def _session_affords(
    db: AsyncSession,
    job: ClassifyGaps | DraftGaps,
    source: _SessionSources,
    stage: Literal["classify", "draft"],
) -> bool:
    assert job.improvement_run_id is not None
    run = await improvement_repo.get_run(
        db, job.improvement_run_id, organization_id=job.organization_id
    )
    assert run is not None, "the source check resolved its parent"
    price = await KnowledgeGapService(db).improvement_estimate(
        source.ctx,
        source.knowledge_base_ids,
        source.message_ids,
        stage=stage,
        source_run_ids=source.run_ids,
    )
    spent = await improvement_repo.spent(db, run.id, organization_id=job.organization_id)
    pipeline = ImprovementPipelineService(db)
    org_left = await pipeline.evals._org_left(source.ctx)
    if not rules.affordable(spent=spent, step_estimate=price, budget=run.budget_usd) or (
        org_left is not None and price > org_left
    ):
        await pipeline._move(
            run,
            rules.Transition(
                ImprovementStatus.STOPPED, ImprovementStage(run.stage), StopReason.BUDGET
            ),
        )
        return False
    return True


async def _classify_session(job: ClassifyGaps) -> int:
    await change_feed.connect_in_worker()
    async with get_worker_db_context() as db:
        source = await _session_sources(db, job, ImprovementStage.CLASSIFYING)
        if not await _session_affords(db, job, source, "classify"):
            return 0
    misses = 0
    for kb_id in source.knowledge_base_ids:
        for _ in range(CLASSIFY_PER_REQUEST // CLASSIFY_BATCH):
            async with get_worker_db_context() as db:
                current = await _session_sources(db, job, ImprovementStage.CLASSIFYING)
                if kb_id not in current.knowledge_base_ids or not current.message_ids:
                    break
                read, found = await KnowledgeGapService(db).classify_batch(
                    current.ctx,
                    kb_id,
                    message_ids=current.message_ids,
                    improvement_run_id=job.improvement_run_id,
                )
            misses += found
            if read < CLASSIFY_BATCH:
                break
    await change_feed.publish_knowledge_gaps_grouped(job.organization_id)
    return misses


async def _record_session_embeddings(ledger: SpendLedger, job: DraftGaps) -> None:
    # The system runner owns model ledgers. This outer ledger contains grouping
    # embeddings only, including calls made before a later failure.
    if not ledger.entries:
        return
    async with get_worker_db_context() as db:
        for model in dict.fromkeys(entry.model_name for entry in ledger.entries):
            entries = [entry for entry in ledger.entries if entry.model_name == model]
            await ingestion_spend_repo.record(
                db,
                organization_id=job.organization_id,
                rag_document_id=None,
                improvement_run_id=job.improvement_run_id,
                model=model,
                input_tokens=sum(entry.input_tokens for entry in entries),
                output_tokens=sum(entry.output_tokens for entry in entries),
                cost_usd=sum((entry.cost_usd for entry in entries), Decimal(0)),
                cost_is_partial=any(not entry.priced for entry in entries),
            )


async def _draft_session(job: DraftGaps) -> int:
    session_id = job.improvement_run_id
    assert session_id is not None
    await change_feed.connect_in_worker()
    async with get_worker_db_context() as db:
        source = await _session_sources(db, job, ImprovementStage.DRAFTING)
        if not await _session_affords(db, job, source, "draft"):
            return 0
    ledger = SpendLedger(organization_id=job.organization_id)
    drafted = too_few_askers = 0
    try:
        with metered_by(ledger):
            for kb_id in source.knowledge_base_ids:
                async with get_worker_db_context() as db:
                    current = await _session_sources(db, job, ImprovementStage.DRAFTING)
                    if kb_id not in current.knowledge_base_ids:
                        continue
                    await KnowledgeGapService(db).group_pending(
                        organization_id=job.organization_id,
                        knowledge_base_id=kb_id,
                        source_run_ids=current.run_ids,
                    )
            async with get_worker_db_context() as db:
                current = await _session_sources(db, job, ImprovementStage.DRAFTING)
                topics = await KnowledgeGapService(db).topics_to_draft(
                    current.ctx, current.knowledge_base_ids, current.message_ids
                )
            for topic_id in topics[:DRAFTS_PER_ROUND]:
                try:
                    async with get_worker_db_context() as db:
                        current = await _session_sources(db, job, ImprovementStage.DRAFTING)
                        await KnowledgeGapService(db).draft(
                            current.ctx,
                            topic_id,
                            automatic=True,
                            improvement_run_id=job.improvement_run_id,
                            source_run_ids=current.run_ids,
                        )
                except NotFoundError:
                    continue
                except BadRequestError as refused:
                    if not {"askers", "draft_author"} & set(refused.details or {}):
                        raise
                    too_few_askers += "askers" in (refused.details or {})
                    continue
                drafted += 1
    finally:
        await _record_session_embeddings(ledger, job)
    async with get_worker_db_context() as db:
        await ImprovementPipelineService(db).drafts_written(
            session_id,
            organization_id=job.organization_id,
            drafted=drafted,
            too_few_askers=too_few_askers,
        )
    await change_feed.publish_knowledge_gaps_grouped(job.organization_id)
    return drafted
