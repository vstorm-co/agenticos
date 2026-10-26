"""Authoring assistant routes - asking it about an agent or a skill, and deciding what it proposed.

Starting is two calls, as an eval is: `estimate` writes nothing and shows what
would be read and spent, and the same body posted to the collection starts it.
Every route is per-resource, so none carries a role gate: the service resolves
access to the agent or the skill through its grants, and to the improver.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Auth, AuthoringSvc, require
from app.core.permissions import Perm
from app.schemas.authoring import (
    AgentAuthoringRead,
    AuthoringEstimate,
    AuthoringRequestRead,
    AuthoringStart,
    AuthoringWaiting,
    DecisionRead,
    HunkDecision,
    IdeaDecision,
    ProposalCheck,
    ProposedSkill,
    ProposedSkillCreated,
)
from app.schemas.eval_run import EvalRunEstimate, EvalRunRead

router = APIRouter()


@router.get(
    "/authoring/waiting",
    response_model=AuthoringWaiting,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def read_waiting_suggestions(service: AuthoringSvc, ctx: Auth) -> Any:
    """Agents the caller may edit with suggestions waiting, and pending skill changes."""
    return await service.waiting(ctx)


@router.get("/agents/{agent_id}/authoring", response_model=AgentAuthoringRead)
async def read_agent_authoring(agent_id: UUID, service: AuthoringSvc, ctx: Auth) -> Any:
    """The suggestions waiting for this agent's draft, and the assistant's latest requests.

    A quote from a run is included only for a caller holding `runs:view`.
    """
    return await service.for_agent(ctx, agent_id)


@router.post("/agents/{agent_id}/authoring/estimate", response_model=AuthoringEstimate)
async def estimate_agent_authoring(
    agent_id: UUID, data: AuthoringStart, service: AuthoringSvc, ctx: Auth
) -> Any:
    """How many runs an Improve or Verify would read, and what it would cost. Writes nothing."""
    return await service.estimate_agent(ctx, agent_id, data)


@router.post(
    "/agents/{agent_id}/authoring",
    response_model=AuthoringRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_agent_authoring(
    agent_id: UUID, data: AuthoringStart, service: AuthoringSvc, ctx: Auth
) -> Any:
    """Start an Improve or Verify in the background.

    Refused with 403 while AI assistance is off, 400 with nothing to read or
    nothing to verify, and 402 when the estimate is more than a budget has left.
    """
    return await service.start_agent(ctx, agent_id, data)


@router.post("/agents/{agent_id}/authoring/hunks/{hunk_id}", response_model=DecisionRead)
async def decide_agent_suggestion(
    agent_id: UUID, hunk_id: UUID, data: HunkDecision, service: AuthoringSvc, ctx: Auth
) -> Any:
    """Accept a suggestion into the draft, dismiss it, or undo either. Nothing publishes.

    409 when the suggestions were replaced or published, or somebody decided this
    one first; 400 when it no longer fits the draft.
    """
    return await service.decide(ctx, agent_id, hunk_id, data)


@router.post(
    "/agents/{agent_id}/authoring/requests/{request_id}/ideas/{index}/skill",
    response_model=ProposedSkillCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_proposed_skill(
    agent_id: UUID,
    request_id: UUID,
    index: int,
    data: ProposedSkill,
    service: AuthoringSvc,
    ctx: Auth,
) -> Any:
    """Create a new skill the assistant proposed but did not record, and add it to the draft.

    `index` is the idea's place in the request report's `rejected` list. The skill
    goes into the organization's library and is bound to the agent's draft; the
    agent uses it once the draft is published. A second call answers with the same
    skill. 403 without `skills:edit`; 409 when the name is taken.
    """
    return await service.create_proposed_skill(ctx, agent_id, request_id, index, data)


@router.post(
    "/agents/{agent_id}/authoring/requests/{request_id}/ideas/{index}/decision",
    response_model=AgentAuthoringRead,
)
async def decide_proposed_skill(
    agent_id: UUID,
    request_id: UUID,
    index: int,
    data: IdeaDecision,
    service: AuthoringSvc,
    ctx: Auth,
) -> Any:
    """Dismiss a new skill the assistant proposed but did not record, or undo that.

    `index` is the idea's place in the request report's `rejected` list. A dismissed
    idea stays on the report, marked `dismissed`. 400 for one already created as a
    skill.
    """
    return await service.decide_idea(ctx, agent_id, request_id, index, data)


@router.post("/agents/{agent_id}/authoring/dismiss", response_model=AgentAuthoringRead)
async def dismiss_agent_suggestions(agent_id: UUID, service: AuthoringSvc, ctx: Auth) -> Any:
    """Dismiss every suggestion still waiting."""
    return await service.dismiss_all(ctx, agent_id)


@router.post("/agents/{agent_id}/authoring/check/estimate", response_model=EvalRunEstimate)
async def estimate_suggestion_check(
    agent_id: UUID, data: ProposalCheck, service: AuthoringSvc, ctx: Auth
) -> Any:
    """What checking the waiting suggestions against a dataset would cost. Writes nothing."""
    return await service.estimate_check(ctx, agent_id, data)


@router.post(
    "/agents/{agent_id}/authoring/check",
    response_model=EvalRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def check_agent_suggestions(
    agent_id: UUID, data: ProposalCheck, service: AuthoringSvc, ctx: Auth
) -> Any:
    """Run a dataset against the draft as it would be with every waiting suggestion accepted.

    The published version runs beside it, and the cases taken from the
    suggestions' own evidence are left out. The draft does not change.
    """
    return await service.check(ctx, agent_id, data)


@router.post("/skills/{skill_id}/authoring/estimate", response_model=AuthoringEstimate)
async def estimate_skill_authoring(
    skill_id: UUID, data: AuthoringStart, service: AuthoringSvc, ctx: Auth
) -> Any:
    """How many runs an Improve on this skill would read, and what it would cost."""
    return await service.estimate_skill(ctx, skill_id, data)


@router.post(
    "/skills/{skill_id}/authoring",
    response_model=AuthoringRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_skill_authoring(
    skill_id: UUID, data: AuthoringStart, service: AuthoringSvc, ctx: Auth
) -> Any:
    """Start an Improve on a skill. Its proposal waits under Skills like any other change."""
    return await service.start_skill(ctx, skill_id, data)


@router.get("/skills/{skill_id}/authoring", response_model=list[AuthoringRequestRead])
async def list_skill_authoring(skill_id: UUID, service: AuthoringSvc, ctx: Auth) -> Any:
    """The assistant's latest requests on this skill, newest first."""
    return await service.for_skill(ctx, skill_id)


@router.post("/skills/{skill_id}/authoring/check/estimate", response_model=EvalRunEstimate)
async def estimate_skill_check(
    skill_id: UUID, data: ProposalCheck, service: AuthoringSvc, ctx: Auth
) -> Any:
    """What checking a pending change to this skill on one agent would cost. Writes nothing."""
    return await service.estimate_skill_check(ctx, skill_id, data)


@router.post(
    "/skills/{skill_id}/authoring/check",
    response_model=EvalRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def check_skill_change(
    skill_id: UUID, data: ProposalCheck, service: AuthoringSvc, ctx: Auth
) -> Any:
    """Run a dataset on an agent using the skill, serving the proposed body in its place.

    Applying a skill change is live for every agent bound to it, so it is checked
    first. The agent runs its published version on both sides.
    """
    return await service.check_skill(ctx, skill_id, data)


@router.post("/context/{context_id}/authoring/estimate", response_model=AuthoringEstimate)
async def estimate_context_authoring(
    context_id: UUID, data: AuthoringStart, service: AuthoringSvc, ctx: Auth
) -> Any:
    """How many runs an Improve on this context file would read, and what it would cost."""
    return await service.estimate_context(ctx, context_id, data)


@router.post(
    "/context/{context_id}/authoring",
    response_model=AuthoringRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_context_authoring(
    context_id: UUID, data: AuthoringStart, service: AuthoringSvc, ctx: Auth
) -> Any:
    """Start an Improve on a context file. Its proposal waits on the file's page."""
    return await service.start_context(ctx, context_id, data)


@router.get("/context/{context_id}/authoring", response_model=list[AuthoringRequestRead])
async def list_context_authoring(context_id: UUID, service: AuthoringSvc, ctx: Auth) -> Any:
    """The assistant's latest requests on this context file, newest first."""
    return await service.for_context(ctx, context_id)


@router.post("/context/{context_id}/authoring/check/estimate", response_model=EvalRunEstimate)
async def estimate_context_check(
    context_id: UUID, data: ProposalCheck, service: AuthoringSvc, ctx: Auth
) -> Any:
    """What checking a pending change to this file on one agent would cost. Writes nothing."""
    return await service.estimate_context_check(ctx, context_id, data)


@router.post(
    "/context/{context_id}/authoring/check",
    response_model=EvalRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def check_context_change(
    context_id: UUID, data: ProposalCheck, service: AuthoringSvc, ctx: Auth
) -> Any:
    """Run a dataset on an agent using the file, serving the proposed body in its place.

    Applying a context change is live for every agent bound to the file, so it is
    checked first. The agent runs its published version on both sides.
    """
    return await service.check_context(ctx, context_id, data)
