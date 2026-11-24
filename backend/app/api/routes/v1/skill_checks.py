"""Checking a change to a skill on every agent of the line it would change.

Per-resource routes: the skill's own access decides, through the service, so a
member holding an edit grant on the skill is not refused by a role gate first.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, SkillCheckSvc, require
from app.api.public_api import ASSISTANT
from app.core.permissions import Perm
from app.schemas.dataset import DatasetRead
from app.schemas.skill_check import (
    SkillCheckApplied,
    SkillCheckApply,
    SkillCheckAwaiting,
    SkillCheckEstimate,
    SkillCheckFork,
    SkillCheckForked,
    SkillCheckList,
    SkillCheckRead,
    SkillCheckRequest,
    SkillTestSetStart,
    SkillUpdateCheck,
)

router = APIRouter()
awaiting = APIRouter(prefix="/skill-checks", dependencies=[ASSISTANT])


@awaiting.get(
    "/awaiting",
    response_model=list[SkillCheckAwaiting],
    dependencies=[Depends(require(Perm.RUNS_VIEW))],
)
async def list_skill_checks_awaiting(service: SkillCheckSvc, ctx: Auth) -> Any:
    """Checks a person started, by hand or on a proposal, still running or waiting for a
    decision, on skills the caller may edit, for "Waiting for you"."""
    return await service.awaiting(ctx)


@router.post(
    "/{skill_id}/checks/estimate", response_model=SkillCheckEstimate, dependencies=[ASSISTANT]
)
async def estimate_check(
    skill_id: UUID, data: SkillCheckRequest, service: SkillCheckSvc, ctx: Auth
) -> Any:
    """Which agents a check would run, on which questions, and what it would cost.

    Agents the caller may not see are counted, never named. An agent that could
    not be run - no access, no questions, no budget left - says why before anything
    is spent.
    """
    return await service.estimate(ctx, skill_id, data)


@router.post(
    "/{skill_id}/checks",
    response_model=SkillCheckRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[ASSISTANT],
)
async def start_check(
    skill_id: UUID, data: SkillCheckRequest, service: SkillCheckSvc, ctx: Auth
) -> Any:
    """Start checking a change: each agent of the line answers with the stored text and with
    the change, its published version otherwise unchanged. Each agent's share is billed
    to that agent."""
    return await service.start(ctx, skill_id, data)


@router.post(
    "/{skill_id}/agents/{agent_id}/update-check/estimate",
    response_model=SkillCheckEstimate,
    dependencies=[ASSISTANT],
)
async def estimate_update_check(
    skill_id: UUID, agent_id: UUID, data: SkillUpdateCheck, service: SkillCheckSvc, ctx: Auth
) -> Any:
    """What checking main's newest version on one pinned agent would run and cost.

    400 when the agent is not pinned to a version of this skill, 409 when it reads
    main's newest version already.
    """
    return await service.estimate_update(ctx, skill_id, agent_id, data)


@router.post(
    "/{skill_id}/agents/{agent_id}/update-check",
    response_model=SkillCheckRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[ASSISTANT],
)
async def start_update_check(
    skill_id: UUID, agent_id: UUID, data: SkillUpdateCheck, service: SkillCheckSvc, ctx: Auth
) -> Any:
    """Check main's newest version on one pinned agent, against the version it stays on.

    Billed to that agent. Accepted with `PUT .../agents/{agent_id}/binding` naming this
    check, which moves the agent to main unless the newer version made it worse.
    """
    return await service.start_update(ctx, skill_id, agent_id, data)


@router.get("/{skill_id}/checks", response_model=SkillCheckList, dependencies=[ASSISTANT])
async def list_checks(
    skill_id: UUID,
    service: SkillCheckSvc,
    ctx: Auth,
    fork_id: UUID | None = Query(None, description="A fork's checks; main's when unset"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    """A line's checks, newest first."""
    return await service.list_checks(ctx, skill_id, fork_id=fork_id, skip=skip, limit=limit)


@router.get(
    "/{skill_id}/checks/{check_id}", response_model=SkillCheckRead, dependencies=[ASSISTANT]
)
async def read_check(skill_id: UUID, check_id: UUID, service: SkillCheckSvc, ctx: Auth) -> Any:
    return await service.read(ctx, skill_id, check_id)


@router.post(
    "/{skill_id}/checks/{check_id}/cancel", response_model=SkillCheckRead, dependencies=[ASSISTANT]
)
async def cancel_check(skill_id: UUID, check_id: UUID, service: SkillCheckSvc, ctx: Auth) -> Any:
    return await service.cancel(ctx, skill_id, check_id)


@router.post(
    "/{skill_id}/checks/{check_id}/apply",
    response_model=SkillCheckApplied,
    dependencies=[ASSISTANT],
)
async def apply_check(
    skill_id: UUID, check_id: UUID, data: SkillCheckApply, service: SkillCheckSvc, ctx: Auth
) -> Any:
    """Make the checked text the line's newest version.

    When it made agents worse, `pin_worse` first keeps each of them, as a new
    published version, on the version it reads now. Agents that could not be
    checked are acknowledged with `acknowledge_unknown`.
    """
    return await service.apply(ctx, skill_id, check_id, data)


@router.post(
    "/{skill_id}/checks/{check_id}/fork",
    response_model=SkillCheckForked,
    status_code=status.HTTP_201_CREATED,
    dependencies=[ASSISTANT],
)
async def fork_check(
    skill_id: UUID, check_id: UUID, data: SkillCheckFork, service: SkillCheckSvc, ctx: Auth
) -> Any:
    """Make the checked text a fork for the agents picked, by default the ones it helped; main
    stays as it is."""
    return await service.fork(ctx, skill_id, check_id, data)


@router.post(
    "/{skill_id}/checks/{check_id}/discard", response_model=SkillCheckRead, dependencies=[ASSISTANT]
)
async def discard_check(skill_id: UUID, check_id: UUID, service: SkillCheckSvc, ctx: Auth) -> Any:
    """Refuse the change, keeping the record of what it found."""
    return await service.discard(ctx, skill_id, check_id)


@router.get("/{skill_id}/test-set", response_model=DatasetRead, dependencies=[ASSISTANT])
async def read_test_set(skill_id: UUID, service: SkillCheckSvc, ctx: Auth) -> Any:
    """The skill's own test questions; 404 when it has none yet."""
    return await service.test_set(ctx, skill_id)


@router.post(
    "/{skill_id}/test-set",
    response_model=DatasetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[ASSISTANT],
)
async def create_test_set(
    skill_id: UUID, data: SkillTestSetStart, service: SkillCheckSvc, ctx: Auth
) -> Any:
    """Give the skill its test questions - empty, or from recent answers that loaded it.

    409 when it has them already.
    """
    return await service.create_test_set(ctx, skill_id, data)
