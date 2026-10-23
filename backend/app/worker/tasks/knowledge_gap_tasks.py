"""Grouping knowledge-base misses into topics, and reading answers for more of them.

Agents record their knowledge searches as they run; turning the misses into
topics needs their queries embedded, which is a network call per knowledge base
and has no place on an agent's run. A knowledge base with nothing new waiting
is not visited, so an idle deployment pays one query a pass and no embedding.

Reading answers for the questions a knowledge base could not answer asks a
model, so it runs only when a person asks for it, as them.
"""

import logging
from uuid import UUID

from app.core.exceptions import BadRequestError
from app.db.locks import LockScope, try_hold_subject_on_connection
from app.db.session import get_worker_connection, get_worker_db_context
from app.services import change_feed
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
    decide what everybody is told. Any other refusal - a spent budget, AI
    assistance switched off - ends the job, and what it drafted stays.

    Returns:
        How many topics were drafted.
    """
    for kb_id in job.knowledge_base_ids:
        async with get_worker_db_context() as db:
            await KnowledgeGapService(db).group_pending(
                organization_id=job.organization_id, knowledge_base_id=kb_id
            )
    async with get_worker_db_context() as db:
        service = KnowledgeGapService(db)
        ctx = await service.acting_as(organization_id=job.organization_id, user_id=job.user_id)
        if ctx is None:
            return 0
        topics = await service.topics_to_draft(ctx, job.knowledge_base_ids, job.message_ids)
    drafted = 0
    for topic_id in topics:
        if drafted == DRAFTS_PER_ROUND:
            break
        try:
            async with get_worker_db_context() as db:
                await KnowledgeGapService(db).draft(ctx, topic_id, automatic=True)
        except BadRequestError as refused:
            if "askers" not in (refused.details or {}):
                raise
            continue
        drafted += 1
    return drafted
