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

from prefect import flow

from app.db.locks import LockScope, try_hold_subject_on_connection
from app.db.session import get_worker_connection, get_worker_db_context
from app.services import change_feed
from app.services.knowledge_gaps import (
    CLASSIFY_BATCH,
    CLASSIFY_PER_REQUEST,
    KnowledgeGapService,
)

logger = logging.getLogger(__name__)


@flow(name="group-knowledge-gaps")
async def group_knowledge_gaps_flow(
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


@flow(name="classify-knowledge-gaps")
async def classify_knowledge_gaps_flow(
    organization_id: str, knowledge_base_id: str, user_id: str
) -> int:
    """Read a knowledge base's recent answers for knowledge gaps, as the person who asked.

    One check of a knowledge base at a time: a second one asked for meanwhile
    finds it held and does nothing, since the first reads the same answers.
    Each run's verdicts commit on their own, so a check a budget stops keeps
    what it read. It stops at the first run that ends without an answer, and
    at one that reads fewer answers than it was given, rather than paying to
    read the same ones again.

    Returns:
        How many misses were recorded.
    """
    await change_feed.connect_in_worker()
    org_id, kb_id, asker = UUID(organization_id), UUID(knowledge_base_id), UUID(user_id)
    async with get_worker_connection() as connection:
        held = await try_hold_subject_on_connection(
            connection, LockScope.KNOWLEDGE_GAP_CHECKS_PER_KNOWLEDGE_BASE, kb_id
        )
        if not held:
            logger.info("knowledge_gaps_check_running", extra={"knowledge_base_id": str(kb_id)})
            return 0
        read_any, misses = False, 0
        for _ in range(CLASSIFY_PER_REQUEST // CLASSIFY_BATCH):
            try:
                async with get_worker_db_context() as db:
                    service = KnowledgeGapService(db)
                    ctx = await service.acting_as(organization_id=org_id, user_id=asker)
                    if ctx is None:
                        break
                    read, found = await service.classify_batch(ctx, kb_id)
            except Exception:
                logger.exception(
                    "knowledge_gaps_check_stopped", extra={"knowledge_base_id": str(kb_id)}
                )
                break
            read_any, misses = read_any or read > 0, misses + found
            if read < CLASSIFY_BATCH:
                break
        if misses:
            async with get_worker_db_context() as db:
                await KnowledgeGapService(db).group_pending(
                    organization_id=org_id, knowledge_base_id=kb_id
                )
    if read_any:
        await change_feed.publish_knowledge_gaps_grouped(org_id)
    return misses
