"""Retention and abandoned-capture reconciliation run even when teaching is disabled."""

from datetime import UTC, datetime, timedelta

from app.core.browser_teaching import (
    MAX_GENERATION_SECONDS,
    TeachingGeneration,
    TeachingReason,
    TeachingRefused,
    TeachingState,
)
from app.core.permissions import AuthContext
from app.db.models.browser_teaching import BrowserTeachingSession
from app.db.models.skill_proposal import ProposalStatus
from app.db.session import get_db_context
from app.repositories import browser_teaching as repo
from app.services import live_browse

from . import _access, _refinement
from ._lease import discover
from ._service import audit, erase, expire, matches, pause, require_capture_time


async def _live_capture(row: BrowserTeachingSession, now: datetime) -> None:
    require_capture_time(row, now)
    if row.source == "manual":
        redis = live_browse.credential_redis()
        held = None if redis is None else await discover(redis, row.run_id, row.call_id)
        if held is None or not matches(row, held):
            raise TeachingRefused(TeachingReason.OWNERSHIP_LOST)


async def sweep_browser_teachings() -> int:
    now = datetime.now(UTC)
    abandoned_before = now - timedelta(seconds=MAX_GENERATION_SECONDS + 60)
    async with get_db_context() as db:
        candidates = await repo.sweep_candidates(db, now, abandoned_before)
    processed = 0
    for organization_id, session_id in candidates:
        async with get_db_context() as db:
            row = await repo.session(db, organization_id, session_id, locked=True)
            if row is None:
                continue
            before = (row.status, row.generation_state, row.reason_code, row.revision)
            expire(row, now)
            if row.status == TeachingState.PROPOSED:
                proposal = await repo.proposal_for_source(db, row.organization_id, row.id)
                if (
                    row.expires_at <= now
                    or proposal is None
                    or proposal.status != ProposalStatus.PENDING
                ):
                    row.sanitized_events, row.review, row.procedure = [], None, None
                    row.title, row.allowed_origins = "", []
            elif row.generation_state == TeachingGeneration.GENERATING and (
                row.generation_started_at is not None
                and row.generation_started_at <= abandoned_before
            ):
                row.generation_state = TeachingGeneration.UNKNOWN.value
                row.reason_code = TeachingReason.GENERATION_UNKNOWN.value
                row.revision += 1
            elif (
                row.source == "refinement"
                and row.status == TeachingState.REVIEW
                and not row.verified_success
            ):
                await _refinement.reconcile(db, row)
            elif (
                row.status == TeachingState.RECORDING
                or row.generation_state == TeachingGeneration.QUEUED
            ):
                context = AuthContext(
                    user_id=row.owner_user_id, organization_id=row.organization_id, role="member"
                )
                try:
                    await _access.authorize(
                        db, context, row, live=row.status == TeachingState.RECORDING
                    )
                    if row.status == TeachingState.RECORDING:
                        await _live_capture(row, now)
                except TeachingRefused as refused:
                    if row.source == "refinement":
                        erase(row, TeachingState.DISCARDED, refused.reason)
                    else:
                        pause(row, refused.reason)
                        if row.generation_state == TeachingGeneration.QUEUED:
                            row.generation_state = TeachingGeneration.CANCELLED.value
                            row.reason_code = refused.reason.value
                            row.revision += 1
            # Round-robin the bounded sweep; live sessions cannot starve expired
            # rows beyond the first batch while their owners keep them open.
            row.updated_at = now
            if before != (row.status, row.generation_state, row.reason_code, row.revision):
                await audit(db, row, "browser_teaching.reconciled")
            processed += 1
    return processed
