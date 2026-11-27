"""Scheduled upkeep for the memory ledger (#2090).

Memory is consolidated only where it changed: every write bumps its scope's
revision, and this sweep folds the scopes whose revision is ahead of the last
consolidation. The pass is deterministic - it merges agreement and flags
disagreement, it does not call a model - so an unchanged scope costs nothing and a
retry or a second worker finds the work already done.
"""

import logging

from app.agents.audience import RunAudience
from app.db.session import get_db_context
from app.repositories import memory_claim as claim_repo
from app.services.memory import MemoryService, claims, extraction
from app.services.memory_inbox import classify_memory_inbox, deliver_memory_inbox
from app.worker.jobs import BackfillMemoryObjects, DeliverMemoryInbox, ExtractMemory

logger = logging.getLogger(__name__)

SCOPES_PER_SWEEP = 200
"""How many changed scopes one sweep folds; the rest wait for the next."""


async def extract_memory(payload: ExtractMemory, *, write_notes: bool = True) -> int:
    """Read one finished chat for what is worth remembering. Returns how many claims it recorded."""
    async with get_db_context() as db:
        if payload.audience_user_id is not None:
            return await extraction.extract(
                db,
                payload.organization_id,
                payload.run_id,
                audience=RunAudience(
                    user_id=payload.audience_user_id,
                    room_key=payload.audience_room_key,
                ),
                write_notes=write_notes,
            )
        return await extraction.extract(
            db, payload.organization_id, payload.run_id, write_notes=write_notes
        )


async def notify_memory_change(payload: DeliverMemoryInbox) -> int:
    async with get_db_context() as db:
        return await deliver_memory_inbox(db, payload)


async def shadow_memory_change(payload: DeliverMemoryInbox) -> int:
    async with get_db_context() as db:
        return await classify_memory_inbox(db, payload)


async def backfill_memory_objects(payload: BackfillMemoryObjects) -> int:
    async with get_db_context() as db:
        return await MemoryService(db).continue_object_backfill(payload)


async def consolidate_memory() -> int:
    """Fold every scope that changed since it was last folded.

    Each scope runs in its own transaction, so one failing scope does not roll back
    the others and is retried by the next sweep.

    Returns:
        How many scopes were consolidated.
    """
    async with get_db_context() as db:
        pending = [
            (state.organization_id, state.scope_key)
            for state in await claim_repo.scopes_with_changes(db, limit=SCOPES_PER_SWEEP)
        ]
    done = 0
    for organization_id, scope_key in pending:
        try:
            async with get_db_context() as db:
                result = await claims.consolidate(
                    db, organization_id=organization_id, scope_key=scope_key
                )
        except Exception:
            logger.exception("Memory consolidation failed for %s", scope_key)
            continue
        done += int(result.ran)
    if done:
        logger.info("Memory sweep: %d scope(s) consolidated", done)
    return done
