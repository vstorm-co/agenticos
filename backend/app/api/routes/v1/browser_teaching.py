"""Teach a task: record, review and propose a browser demonstration as a skill (#113).

No route accepts recorder events. Steps are appended only by the capture in the
run's worker, at the held tab's input boundary. Every route refuses while the
deployment flag is off, except read, stop, pause and discard, which only close
or erase. A row that is not the caller's own answers `404`, like a missing one.

Review edits labels and parameter names only. Propose queues one proposal build;
the result is an ordinary pending skill proposal, applied or discarded through
`/skill-changes`. Nothing here publishes or binds a skill.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.api.deps import Auth, BrowserTeachingSvc, require
from app.core.browser_teaching import revision_from_if_match
from app.core.permissions import Perm
from app.schemas.browser_teaching import (
    TeachingEdit,
    TeachingPropose,
    TeachingRead,
    TeachingReview,
    TeachingStart,
)

router = APIRouter()


@router.post(
    "",
    response_model=TeachingRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.SKILLS_EDIT))],
)
async def start_browser_teaching(
    body: TeachingStart,
    ctx: Auth,
    service: BrowserTeachingSvc,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=255,
            description="A retry under the same key returns the same session.",
        ),
    ] = None,
) -> Any:
    """Start recording in a browser view the caller holds now.

    The caller must have taken over the view as the run's own person; the run must
    be running and theirs. Refused with `browser_not_held` otherwise.
    """
    return await service.start(ctx, body, idempotency_key)


@router.get("/{session_id}", response_model=TeachingRead)
async def get_browser_teaching(session_id: UUID, ctx: Auth, service: BrowserTeachingSvc) -> Any:
    """The caller's own session, with its sanitized structural steps."""
    return await service.get(ctx, session_id)


@router.patch("/{session_id}", response_model=TeachingRead)
async def change_browser_teaching(
    session_id: UUID,
    body: TeachingEdit,
    ctx: Auth,
    service: BrowserTeachingSvc,
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=32)] = None,
) -> Any:
    """Pause, resume, or replace the review's labels and parameter names.

    `If-Match` must name the current revision, or the answer is `409`. Sending the
    stored review again returns the session unchanged.
    """
    revision = revision_from_if_match(if_match)
    if isinstance(body, TeachingReview):
        return await service.review(ctx, session_id, body, revision)
    return await service.change(ctx, session_id, body, revision)


@router.post(
    "/{session_id}/propose", response_model=TeachingRead, status_code=status.HTTP_202_ACCEPTED
)
async def propose_browser_teaching(
    session_id: UUID,
    body: TeachingPropose,
    ctx: Auth,
    service: BrowserTeachingSvc,
    if_match: Annotated[str | None, Header(alias="If-Match", max_length=32)] = None,
) -> Any:
    """Queue one skill proposal from the reviewed steps, parameter names and allowed origins.

    Checks authority and the organization's budget first, and the build checks
    them again. Repeating it for the same name returns the same session and
    never a second proposal.
    """
    return await service.propose(ctx, session_id, body, revision_from_if_match(if_match))


@router.post("/{session_id}/stop", response_model=TeachingRead)
async def stop_browser_teaching(session_id: UUID, ctx: Auth, service: BrowserTeachingSvc) -> Any:
    """Close capture and enter review. Repeating it returns the same review state."""
    return await service.stop(ctx, session_id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def discard_browser_teaching(
    session_id: UUID, ctx: Auth, service: BrowserTeachingSvc
) -> None:
    """Erase the recording. It does not undo anything done in the browser."""
    await service.discard(ctx, session_id)
