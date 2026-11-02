"""Start, follow and take the steps of an improvement session on one line of a skill."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, SkillImprovementSvc, require
from app.core.permissions import Perm
from app.schemas.authoring import HunkRead
from app.schemas.improvement import ChangeEdit, ImprovementDiscard, ImprovementSelection
from app.schemas.skill_improvement import (
    SkillContinuationConsent,
    SkillContinuationEstimate,
    SkillImprovementAwaiting,
    SkillImprovementEstimate,
    SkillImprovementProblems,
    SkillImprovementRead,
    SkillImprovementStart,
    SkillImprovementTarget,
)

router = APIRouter(prefix="/skills/{skill_id}/improvements")
sessions = APIRouter(prefix="/skill-improvements")


@sessions.get(
    "/awaiting",
    response_model=list[SkillImprovementAwaiting],
    dependencies=[Depends(require(Perm.RUNS_VIEW))],
)
async def list_skill_improvements_awaiting(service: SkillImprovementSvc, ctx: Auth) -> Any:
    """Skill sessions waiting for a person - at a stop or with a result - on skills the caller
    may read, for "Waiting for you"."""
    return await service.awaiting(ctx)


@router.post("/estimate", response_model=SkillImprovementEstimate)
async def estimate_skill_improvement(
    skill_id: UUID, data: SkillImprovementTarget, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """What a session on the line would read and cost before it first waits for a person.

    Needs `runs:view` and edit access to the skill. A fork of another skill is a 400 on
    `fork_id`.
    """
    return await service.estimate(ctx, skill_id, data)


@router.post("", response_model=SkillImprovementRead, status_code=status.HTTP_201_CREATED)
async def start_skill_improvement(
    skill_id: UUID, data: SkillImprovementStart, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """Queue a session on the line: 409 when the line has an open one, 402 when the spending
    limit or a budget does not cover grouping the problems."""
    return await service.start(ctx, skill_id, data)


@router.get("", response_model=list[SkillImprovementRead])
async def list_skill_improvements(
    skill_id: UUID,
    service: SkillImprovementSvc,
    ctx: Auth,
    fork_id: UUID | None = Query(None, description="One fork's sessions"),
    main: bool = Query(False, description="The main line's sessions only"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The skill's sessions, newest first: every line, the main line, or one fork."""
    return await service.list_for_skill(
        ctx, skill_id, fork_id=fork_id, main_only=main, skip=skip, limit=limit
    )


@router.get("/{run_id}", response_model=SkillImprovementRead)
async def read_skill_improvement(
    skill_id: UUID, run_id: UUID, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """The session: its steps, attempts, costs and timeline."""
    return await service.read(ctx, skill_id, run_id)


@router.get("/{run_id}/evidence", response_model=SkillImprovementProblems)
async def read_skill_improvement_problems(
    skill_id: UUID, run_id: UUID, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """Understand: the problems the line's bad answers show, with the agents each occurred in.

    Agents the caller may not see are counted, never named.
    """
    return await service.problems(ctx, skill_id, run_id)


@router.get("/{run_id}/changes", response_model=list[HunkRead])
async def read_skill_improvement_changes(
    skill_id: UUID,
    run_id: UUID,
    service: SkillImprovementSvc,
    ctx: Auth,
    attempt: int | None = Query(None, ge=1, description="An earlier attempt's changes"),
) -> Any:
    """The edits an attempt proposed to the line's text: `skill_body` and `skill_description`."""
    return await service.changes(ctx, skill_id, run_id, attempt=attempt)


@router.put("/{run_id}/changes/{hunk_id}", response_model=HunkRead)
async def edit_skill_improvement_change(
    skill_id: UUID,
    run_id: UUID,
    hunk_id: UUID,
    data: ChangeEdit,
    service: SkillImprovementSvc,
    ctx: Auth,
) -> Any:
    """Reword one proposed edit while the session waits at Changes; the check measures it."""
    return await service.edit_change(ctx, skill_id, run_id, hunk_id, data)


@router.put("/{run_id}/selection", response_model=SkillImprovementRead)
async def choose_skill_improvement_changes(
    skill_id: UUID,
    run_id: UUID,
    data: ImprovementSelection,
    service: SkillImprovementSvc,
    ctx: Auth,
) -> Any:
    """Choose which of the attempt's edits its check measures."""
    return await service.choose_changes(ctx, skill_id, run_id, data)


@router.post("/{run_id}/continue/estimate", response_model=SkillContinuationEstimate)
async def estimate_skill_improvement_continuation(
    skill_id: UUID, run_id: UUID, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """The price of the step a person may take now: a proposal, or Try again."""
    return await service.estimate_continuation(ctx, skill_id, run_id)


@router.post("/{run_id}/continue", response_model=SkillImprovementRead)
async def continue_skill_improvement(
    skill_id: UUID,
    run_id: UUID,
    data: SkillContinuationConsent,
    service: SkillImprovementSvc,
    ctx: Auth,
) -> Any:
    """Take the next step, or try again with a note: 409 when its price moved since the quote."""
    return await service.continue_run(ctx, skill_id, run_id, data)


@router.post("/{run_id}/retry", response_model=SkillImprovementRead)
async def retry_skill_improvement(
    skill_id: UUID, run_id: UUID, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """Run a failed step again, within the session's spending limit."""
    return await service.retry(ctx, skill_id, run_id)


@router.post("/{run_id}/cancel", response_model=SkillImprovementRead)
async def cancel_skill_improvement(
    skill_id: UUID, run_id: UUID, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """Stop the session where it is."""
    return await service.cancel(ctx, skill_id, run_id)


@router.post("/{run_id}/discard", response_model=SkillImprovementRead)
async def discard_skill_improvement(
    skill_id: UUID,
    run_id: UUID,
    data: ImprovementDiscard,
    service: SkillImprovementSvc,
    ctx: Auth,
) -> Any:
    """End the session without applying anything: its creator or an organization admin."""
    return await service.discard(ctx, skill_id, run_id, data)
