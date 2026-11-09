"""Start, follow and take the steps of an improvement session on one line of a skill."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, SkillCatchUpSvc, SkillImprovementSvc, require
from app.api.public_api import ASSISTANT
from app.core.permissions import Perm
from app.db.models.skill_improvement import SkillImprovementPurpose
from app.schemas.authoring import HunkRead
from app.schemas.improvement import ChangeEdit, ImprovementDiscard, ImprovementSelection
from app.schemas.skill_improvement import (
    SkillContinuationConsent,
    SkillContinuationEstimate,
    SkillContinue,
    SkillImprovementApplied,
    SkillImprovementApply,
    SkillImprovementAwaiting,
    SkillImprovementEstimate,
    SkillImprovementFork,
    SkillImprovementForked,
    SkillImprovementProblems,
    SkillImprovementRead,
    SkillImprovementReturn,
    SkillImprovementReturned,
    SkillImprovementStart,
    SkillImprovementTarget,
    SkillMergeEstimate,
    SkillMergeStart,
)
from app.schemas.skill_merge import (
    MergeDescriptionEdit,
    MergeFilePick,
    MergePartEdit,
    SkillMergeRead,
)

router = APIRouter(prefix="/skills/{skill_id}/improvements", dependencies=[ASSISTANT])
sessions = APIRouter(prefix="/skill-improvements", dependencies=[ASSISTANT])
merges = APIRouter(prefix="/skills/{skill_id}/forks/{fork_id}", dependencies=[ASSISTANT])


@merges.post("/catch-up/estimate", response_model=SkillMergeEstimate)
async def estimate_skill_catch_up(
    skill_id: UUID, fork_id: UUID, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """What catching the fork up with main would merge, and what proposing the conflicts'
    texts costs. Needs `runs:view` and edit access to the skill; 409 when main has nothing
    the fork lacks, 400 for an archived fork."""
    return await service.estimate_merge(ctx, skill_id, fork_id, SkillImprovementPurpose.CATCH_UP)


@merges.post("/catch-up", response_model=SkillImprovementRead, status_code=status.HTTP_201_CREATED)
async def start_skill_catch_up(
    skill_id: UUID, fork_id: UUID, data: SkillMergeStart, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """Start a session on the fork that merges main's newest version into it. 409 when there
    is nothing to merge or the fork has an open session, 402 when the spending limit does
    not cover proposing the conflicts' texts."""
    return await service.start_merge(ctx, skill_id, fork_id, SkillImprovementPurpose.CATCH_UP, data)


@merges.post("/to-main/estimate", response_model=SkillMergeEstimate)
async def estimate_skill_to_main(
    skill_id: UUID, fork_id: UUID, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """What moving the fork's changes to main would merge, and what proposing the
    conflicts' texts costs. 409 when the fork has no version of its own."""
    return await service.estimate_merge(ctx, skill_id, fork_id, SkillImprovementPurpose.TO_MAIN)


@merges.post("/to-main", response_model=SkillImprovementRead, status_code=status.HTTP_201_CREATED)
async def start_skill_to_main(
    skill_id: UUID, fork_id: UUID, data: SkillMergeStart, service: SkillImprovementSvc, ctx: Auth
) -> Any:
    """Start a session on main that merges the fork's newest version into it. 409 when there
    is nothing to merge or main has an open session, 402 as for a catch-up."""
    return await service.start_merge(ctx, skill_id, fork_id, SkillImprovementPurpose.TO_MAIN, data)


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
    skill_id: UUID,
    run_id: UUID,
    service: SkillImprovementSvc,
    ctx: Auth,
    data: SkillContinue | None = None,
) -> Any:
    """The price of the step a person may take now: a proposal after Understand, the check
    of the chosen changes across the line's agents after Changes, or Try again."""
    return await service.estimate_continuation(ctx, skill_id, run_id, data or SkillContinue())


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


@router.post("/{run_id}/apply", response_model=SkillImprovementApplied)
async def apply_skill_improvement(
    skill_id: UUID,
    run_id: UUID,
    data: SkillImprovementApply,
    service: SkillImprovementSvc,
    ctx: Auth,
) -> Any:
    """Make the checked text the line's newest version.

    A result with a worse agent applies only with `pin_worse`, which keeps each such agent
    on the version it reads now, as a new published version; that needs `agents:publish`
    on each. Agents that could not be checked need `acknowledge_unknown`. 409 while the
    check runs or once the result was decided.
    """
    return await service.apply(ctx, skill_id, run_id, data)


@router.post("/{run_id}/return-to-main", response_model=SkillImprovementReturned)
async def return_skill_improvement_to_main(
    skill_id: UUID,
    run_id: UUID,
    data: SkillImprovementReturn,
    service: SkillImprovementSvc,
    ctx: Auth,
) -> Any:
    """Move a caught-up fork's agents back to main instead of taking the merge in, when
    main alone made nobody worse; the fork is archived once nobody reads it. 400 for a
    session that is not a catch-up, a result that does not offer it, or agents main alone
    could not be checked on and `acknowledge_unknown` does not accept."""
    return await service.return_to_main(ctx, skill_id, run_id, data)


@router.post("/{run_id}/fork", response_model=SkillImprovementForked)
async def fork_skill_improvement(
    skill_id: UUID,
    run_id: UUID,
    data: SkillImprovementFork,
    service: SkillImprovementSvc,
    ctx: Auth,
) -> Any:
    """Make the checked text a new fork for the agents picked, by default the ones it helped;
    main stays as it is.

    Only a session on main forks. 409 while the check runs or once the result was decided.
    """
    return await service.fork(ctx, skill_id, run_id, data)


@router.post("/{run_id}/recheck/estimate", response_model=SkillContinuationEstimate)
async def estimate_skill_improvement_recheck(
    skill_id: UUID,
    run_id: UUID,
    service: SkillImprovementSvc,
    ctx: Auth,
    data: SkillContinue | None = None,
) -> Any:
    """The price of Check again: the result's changes measured on the line as it is now."""
    return await service.estimate_recheck(ctx, skill_id, run_id, data or SkillContinue())


@router.post("/{run_id}/recheck", response_model=SkillImprovementRead)
async def recheck_skill_improvement(
    skill_id: UUID,
    run_id: UUID,
    data: SkillContinuationConsent,
    service: SkillImprovementSvc,
    ctx: Auth,
) -> Any:
    """Check the result's changes again, for a result marked `stale` or one whose decision was
    refused because the line or its agents changed. Writes no new proposal; 409 when the price
    moved since the quote."""
    return await service.recheck(ctx, skill_id, run_id, data)


@router.get(
    "/{run_id}/merge",
    response_model=SkillMergeRead,
)
async def get_skill_merge(skill_id: UUID, run_id: UUID, service: SkillCatchUpSvc, ctx: Auth) -> Any:
    """The three-way merge a session catching a fork up, or moving it to main, works on.

    Each text says which side it comes from; a conflict nobody has settled has no
    result, and the check waits until none is left.
    """
    return await service.read_merge(ctx, skill_id, run_id)


@router.patch(
    "/{run_id}/merge/description",
    response_model=SkillMergeRead,
)
async def edit_skill_merge_description(
    skill_id: UUID, run_id: UUID, data: MergeDescriptionEdit, service: SkillCatchUpSvc, ctx: Auth
) -> Any:
    """Write the merged description, while the session waits at Changes."""
    return await service.edit_description(ctx, skill_id, run_id, data)


@router.patch(
    "/{run_id}/merge/parts/{index}",
    response_model=SkillMergeRead,
)
async def edit_skill_merge_part(
    skill_id: UUID,
    run_id: UUID,
    index: int,
    data: MergePartEdit,
    service: SkillCatchUpSvc,
    ctx: Auth,
) -> Any:
    """Write one part of the merged instructions, while the session waits at Changes."""
    return await service.edit_part(ctx, skill_id, run_id, index, data)


@router.patch(
    "/{run_id}/merge/files",
    response_model=SkillMergeRead,
)
async def pick_skill_merge_file(
    skill_id: UUID, run_id: UUID, data: MergeFilePick, service: SkillCatchUpSvc, ctx: Auth
) -> Any:
    """Keep one side's version of a file, while the session waits at Changes. Taking the
    side the file is absent from drops it."""
    return await service.pick_file(ctx, skill_id, run_id, data)
