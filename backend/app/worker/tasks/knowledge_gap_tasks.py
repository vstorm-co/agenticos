"""Grouping knowledge-base misses into topics, on a schedule.

Agents record their knowledge searches as they run; turning the misses into
topics needs their queries embedded, which is a network call per knowledge base
and has no place on an agent's run. A knowledge base with nothing new waiting
is not visited, so an idle deployment pays one query a pass and no embedding.
"""

import logging
from uuid import UUID

from prefect import flow

from app.db.session import get_worker_db_context
from app.services import change_feed
from app.services.knowledge_gaps import KnowledgeGapService

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
