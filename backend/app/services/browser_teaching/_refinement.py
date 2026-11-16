"""Opt-in owning-run recordings become review suggestions only after task completion."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.browser_teaching import (
    MAX_CAPTURE_SECONDS,
    RETENTION_SECONDS,
    CaptureObservation,
    TeachingAction,
    TeachingGeneration,
    TeachingReason,
    TeachingRefused,
    TeachingState,
    canonical_bytes,
)
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunStatus
from app.db.models.browser_teaching import BrowserTeachingSession
from app.repositories import browser_teaching as repo
from app.schemas.browser_teaching import TeachingRead

from . import _access
from ._lease import TeachingIdentity
from ._service import audit, erase, expire, read, record_action, require_capture_time


def owns(row: BrowserTeachingSession, identity: TeachingIdentity) -> bool:
    return (
        row.source == "refinement"
        and row.organization_id == identity.organization_id
        and row.owner_user_id == identity.user_id
        and row.agent_id == identity.agent_id
        and row.run_id == identity.run_id
        and row.controller_id == identity.controller_id
        and row.call_id == identity.call_id
        and row.tab_id == identity.tab_id
    )


async def start(
    db: AsyncSession, ctx: AuthContext, identity: TeachingIdentity, origin: str
) -> TeachingRead | None:
    admission = await _access.admit(db, ctx, identity, live=True)
    preference = await repo.preference(
        db, identity.organization_id, identity.user_id, identity.agent_id
    )
    if (
        admission.run.test_spec is not None
        or not admission.learning_allowed
        or preference is None
        or not preference.enabled
    ):
        return None
    await _access.target(db, admission.context, None)
    await repo.policy(db, identity.organization_id, locked=True)
    admission = await _access.admit(db, ctx, identity, live=True)
    preference = await repo.preference(
        db, identity.organization_id, identity.user_id, identity.agent_id, locked=True
    )
    if (
        admission.run.test_spec is not None
        or not admission.learning_allowed
        or preference is None
        or not preference.enabled
    ):
        return None
    # The run/call source has one attempt even after a process resumes with a new
    # controller. A new page cannot take over a prior controller's recording.
    session_id = uuid5(identity.run_id, "browser-refinement:" + identity.call_id)
    if (
        await repo.session(db, identity.organization_id, session_id, locked=True) is not None
        or await repo.active(db, identity.organization_id, identity.controller_id) is not None
        or await repo.owner_open_count(db, identity.organization_id, identity.user_id) >= 20
    ):
        return None
    now = datetime.now(UTC)
    row = await repo.create(
        db,
        BrowserTeachingSession(
            id=session_id,
            organization_id=identity.organization_id,
            owner_user_id=identity.user_id,
            agent_id=identity.agent_id,
            run_id=identity.run_id,
            controller_id=identity.controller_id,
            takeover_id=None,
            connection_id=None,
            call_id=identity.call_id,
            tab_id=identity.tab_id,
            title="Browser procedure suggestion",
            allowed_origins=[origin],
            target_skill_id=None,
            target_base_version=None,
            target_base_version_id=None,
            source="refinement",
            verified_success=False,
            browser_completed=False,
            policy_generation=admission.policy.generation,
            preference_generation=preference.generation,
            request_fingerprint=hashlib.sha256(
                canonical_bytes(identity.model_dump(mode="json"))
            ).hexdigest(),
            status=TeachingState.RECORDING.value,
            revision=1,
            sanitized_events=[],
            generation_state=TeachingGeneration.NONE.value,
            capture_ends_at=now + timedelta(seconds=MAX_CAPTURE_SECONDS),
            expires_at=now + timedelta(seconds=RETENTION_SECONDS),
        ),
    )
    record_action(
        row,
        input_id=uuid5(session_id, "0"),
        action="navigate",
        observation=CaptureObservation(origin=origin),
        now=now,
    )
    await db.flush()
    await audit(db, row, "browser_teaching.refinement_started")
    return read(row)


async def authorize_capture(
    db: AsyncSession,
    ctx: AuthContext,
    identity: TeachingIdentity,
    session_id: UUID,
) -> BrowserTeachingSession:
    row = await repo.session(db, identity.organization_id, session_id, locked=True)
    if row is None or not owns(row, identity) or row.status != TeachingState.RECORDING:
        raise TeachingRefused(TeachingReason.OWNERSHIP_LOST)
    require_capture_time(row, datetime.now(UTC))
    await _access.authorize(db, ctx, row, live=True)
    return row


async def append(
    db: AsyncSession,
    ctx: AuthContext,
    identity: TeachingIdentity,
    session_id: UUID,
    *,
    input_id: UUID,
    action: TeachingAction,
    observation: CaptureObservation,
    direction: Literal["up", "down"] | None = None,
) -> TeachingRead:
    row = await repo.session(db, identity.organization_id, session_id, locked=True)
    if row is None or not owns(row, identity):
        raise TeachingRefused(TeachingReason.OWNERSHIP_LOST)
    expire(row, datetime.now(UTC))
    if row.status != TeachingState.RECORDING:
        return read(row)
    await _access.authorize(db, ctx, row, live=True)
    # Only the fixed initial origin is recorded. A redirect cannot widen a saved
    # procedure; a person must choose and review any additional origin manually.
    record_action(
        row,
        input_id=input_id,
        action=action,
        observation=observation,
        direction=direction,
        now=datetime.now(UTC),
    )
    await db.flush()
    return read(row)


async def finish(
    db: AsyncSession,
    ctx: AuthContext,
    identity: TeachingIdentity,
    session_id: UUID,
    *,
    completed: bool,
    reason: TeachingReason = TeachingReason.TASK_NOT_COMPLETED,
) -> TeachingRead | None:
    row = await repo.session(db, identity.organization_id, session_id, locked=True)
    if row is None or not owns(row, identity):
        return None
    expire(row, datetime.now(UTC))
    if row.status not in {TeachingState.RECORDING, TeachingState.PAUSED}:
        return read(row)
    if row.capture_ends_at <= datetime.now(UTC):
        completed, reason = False, TeachingReason.TIME_LIMIT
    if not completed or row.status != TeachingState.RECORDING:
        erase(row, TeachingState.DISCARDED, reason)
    else:
        try:
            admission = await _access.authorize(db, ctx, row, live=False)
        except TeachingRefused as refused:
            erase(row, TeachingState.DISCARDED, refused.reason)
        else:
            if admission.run.status not in {RunStatus.RUNNING.value, RunStatus.COMPLETED.value}:
                erase(row, TeachingState.DISCARDED, TeachingReason.TASK_NOT_COMPLETED)
            else:
                row.browser_completed = True
                row.verified_success = admission.run.status == RunStatus.COMPLETED.value
                row.status = TeachingState.REVIEW.value
                row.reason_code = (
                    None if row.verified_success else TeachingReason.TASK_NOT_COMPLETED.value
                )
                row.revision += 1
    await db.flush()
    await audit(db, row, "browser_teaching.refinement_stopped")
    return read(row)


async def reconcile(db: AsyncSession, row: BrowserTeachingSession) -> None:
    """The worker proves actual run completion; a closed browser alone cannot."""
    context = AuthContext(
        user_id=row.owner_user_id, organization_id=row.organization_id, role="member"
    )
    try:
        admission = await _access.authorize(db, context, row, live=False)
    except TeachingRefused as refused:
        erase(row, TeachingState.DISCARDED, refused.reason)
    else:
        if row.browser_completed and admission.run.status == RunStatus.COMPLETED.value:
            row.verified_success, row.reason_code = True, None
            row.revision += 1
        elif not row.browser_completed or admission.run.status != RunStatus.RUNNING.value:
            erase(row, TeachingState.DISCARDED, TeachingReason.TASK_NOT_COMPLETED)
