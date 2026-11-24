"""The failure-learning loop: mined patterns, the ledger, eval cases, tries.

One router holds both path families, mounted without a prefix the way
`runs.py` is: the org-wide patterns list lives at
`/v1/failure-learning/patterns`, while the per-agent routes live under
`/v1/agents/{agent_id}/failure-learning`. They share one domain and one
service, so splitting them across two modules would split the thing a
reader comes to understand.

Only the org-wide list carries a route gate (`RUNS_VIEW` - it is an
aggregation, not a resource). Every per-agent route delegates to
`FailureLearningService`, which resolves `AGENTS_VIEW` / `AGENTS_EDIT` on
that agent and reports a refusal as "not found" - see the
`permissions-rbac` skill.
"""

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, FailureLearningSvc, limit_agent_eval_run, require
from app.core.permissions import Perm
from app.schemas.failure_learning import (
    EvalCaseCreate,
    EvalCaseList,
    EvalCaseRead,
    EvalTryCreate,
    EvalTryRead,
    FailurePatternList,
    LedgerEntryCreate,
    LedgerEntryList,
    LedgerEntryRead,
    LedgerEntryUpdate,
    ProposalCreate,
    ProposalList,
    ProposalRead,
    ProposalReject,
)

router = APIRouter()


@router.get(
    "/failure-learning/patterns",
    response_model=FailurePatternList,
    dependencies=[Depends(require(Perm.RUNS_VIEW))],
)
async def list_org_patterns(
    service: FailureLearningSvc,
    ctx: Auth,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    agent_id: UUID | None = Query(None),
    model: str | None = Query(None),
    status: str | None = Query(None),
    min_count: int | None = Query(None, ge=1),
) -> Any:
    """Org-wide failure patterns in the last 7 days, grouped by agent, model,
    status and error class. A pattern that has an open ledger entry is marked
    `already_tracked`."""
    return await service.list_org_patterns(
        ctx,
        from_date=from_date,
        to_date=to_date,
        agent_id=agent_id,
        model=model,
        status=status,
        min_count=min_count,
    )


@router.get("/agents/{agent_id}/failure-learning/patterns", response_model=FailurePatternList)
async def list_agent_patterns(
    agent_id: UUID,
    service: FailureLearningSvc,
    ctx: Auth,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    model: str | None = Query(None),
    status: str | None = Query(None),
    min_count: int | None = Query(None, ge=1),
) -> Any:
    """One agent's failure patterns in the last 7 days."""
    return await service.list_agent_patterns(
        ctx,
        agent_id,
        from_date=from_date,
        to_date=to_date,
        model=model,
        status=status,
        min_count=min_count,
    )


@router.get("/agents/{agent_id}/failure-learning/ledger", response_model=LedgerEntryList)
async def list_ledger_entries(
    agent_id: UUID,
    service: FailureLearningSvc,
    ctx: Auth,
    status: str | None = Query(None),
) -> Any:
    """An agent's ledger entries, newest first, with model-scoped entries beside them."""
    return await service.list_ledger(ctx, agent_id, status=status)


@router.post(
    "/agents/{agent_id}/failure-learning/ledger",
    response_model=LedgerEntryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_ledger_entry(
    agent_id: UUID, data: LedgerEntryCreate, service: FailureLearningSvc, ctx: Auth
) -> Any:
    """A pattern, accepted as real and worth a rule."""
    return await service.create_ledger(ctx, agent_id, data)


@router.get(
    "/agents/{agent_id}/failure-learning/ledger/{entry_id}",
    response_model=LedgerEntryRead,
)
async def get_ledger_entry(
    agent_id: UUID, entry_id: UUID, service: FailureLearningSvc, ctx: Auth
) -> Any:
    """One ledger entry, with its eval case count."""
    return await service.get_ledger(ctx, agent_id, entry_id)


@router.patch(
    "/agents/{agent_id}/failure-learning/ledger/{entry_id}",
    response_model=LedgerEntryRead,
)
async def update_ledger_entry(
    agent_id: UUID,
    entry_id: UUID,
    data: LedgerEntryUpdate,
    service: FailureLearningSvc,
    ctx: Auth,
) -> Any:
    """Curate an entry: accept it, dismiss it, rewrite why."""
    return await service.update_ledger(ctx, agent_id, entry_id, data)


@router.delete(
    "/agents/{agent_id}/failure-learning/ledger/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_ledger_entry(
    agent_id: UUID, entry_id: UUID, service: FailureLearningSvc, ctx: Auth
) -> None:
    """Remove an entry. Its eval cases keep what they said."""
    await service.delete_ledger(ctx, agent_id, entry_id)


@router.get("/agents/{agent_id}/failure-learning/eval-cases", response_model=EvalCaseList)
async def list_eval_cases(agent_id: UUID, service: FailureLearningSvc, ctx: Auth) -> Any:
    """An agent's eval cases, oldest first, each with its latest try's verdict."""
    return await service.list_cases(ctx, agent_id)


@router.post(
    "/agents/{agent_id}/failure-learning/eval-cases",
    response_model=EvalCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_eval_case(
    agent_id: UUID, data: EvalCaseCreate, service: FailureLearningSvc, ctx: Auth
) -> Any:
    """A case for an agent: an input, and what its answer should say. An agent
    holds at most 50."""
    return await service.create_case(ctx, agent_id, data)


@router.delete(
    "/agents/{agent_id}/failure-learning/eval-cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_eval_case(
    agent_id: UUID, case_id: UUID, service: FailureLearningSvc, ctx: Auth
) -> None:
    """Remove a case. Tries already made keep what they said then."""
    await service.delete_case(ctx, agent_id, case_id)


@router.post(
    "/agents/{agent_id}/failure-learning/eval-runs",
    response_model=EvalTryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_agent_eval_run)],
)
async def try_eval_cases(
    agent_id: UUID, data: EvalTryCreate, service: FailureLearningSvc, ctx: Auth
) -> Any:
    """Start a try of the named cases: old text against new, per sample. The
    route's rate-limit allowance covers the first run the try starts; the
    service charges the rest the same way."""
    return await service.start_try(ctx, agent_id, data, first_run_charged=True)


@router.get("/agents/{agent_id}/failure-learning/eval-runs/{try_id}", response_model=EvalTryRead)
async def get_eval_run(agent_id: UUID, try_id: UUID, service: FailureLearningSvc, ctx: Auth) -> Any:
    """A try, judged as its runs stand now: each case passed, failed or still going."""
    return await service.get_try(ctx, agent_id, try_id)


@router.post(
    "/agents/{agent_id}/failure-learning/proposals",
    response_model=ProposalRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_proposal(
    agent_id: UUID, data: ProposalCreate, service: FailureLearningSvc, ctx: Auth
) -> Any:
    """Propose a change: new instructions for the agent, or new content for one skill."""
    return await service.create_proposal(ctx, agent_id, data)


@router.get("/agents/{agent_id}/failure-learning/proposals", response_model=ProposalList)
async def list_proposals(
    agent_id: UUID,
    service: FailureLearningSvc,
    ctx: Auth,
    status: str | None = Query(None),
) -> Any:
    """An agent's proposals, newest first. Filtering `status=applied` is the
    applied-changes list, with each entry's eval evidence beside it."""
    return await service.list_proposals(ctx, agent_id, status=status)


@router.get(
    "/agents/{agent_id}/failure-learning/proposals/{proposal_id}",
    response_model=ProposalRead,
)
async def get_proposal(
    agent_id: UUID, proposal_id: UUID, service: FailureLearningSvc, ctx: Auth
) -> Any:
    """One proposal, its eval evidence, and its apply record if applied."""
    return await service.get_proposal(ctx, agent_id, proposal_id)


@router.post(
    "/agents/{agent_id}/failure-learning/proposals/{proposal_id}/apply",
    response_model=ProposalRead,
)
async def apply_proposal(
    agent_id: UUID, proposal_id: UUID, service: FailureLearningSvc, ctx: Auth
) -> Any:
    """Apply a proposal after its eval gate passes."""
    return await service.apply_proposal(ctx, agent_id, proposal_id)


@router.post(
    "/agents/{agent_id}/failure-learning/proposals/{proposal_id}/revert",
    response_model=ProposalRead,
)
async def revert_proposal(
    agent_id: UUID, proposal_id: UUID, service: FailureLearningSvc, ctx: Auth
) -> Any:
    """Restore the skill content snapshotted when the proposal was applied."""
    return await service.revert_proposal(ctx, agent_id, proposal_id)


@router.post(
    "/agents/{agent_id}/failure-learning/proposals/{proposal_id}/reject",
    response_model=ProposalRead,
)
async def reject_proposal(
    agent_id: UUID,
    proposal_id: UUID,
    data: ProposalReject,
    service: FailureLearningSvc,
    ctx: Auth,
) -> Any:
    """Reject a proposal, with the reason - recorded in the audit trail."""
    return await service.reject_proposal(ctx, agent_id, proposal_id, data)
