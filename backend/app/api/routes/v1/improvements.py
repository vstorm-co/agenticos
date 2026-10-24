"""Start, follow and stop an improvement without accepting or publishing it."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, ImprovementSvc
from app.schemas.eval_run import EvalRunRead
from app.schemas.improvement import (
    AttributionConsent,
    AttributionEstimate,
    ImprovementEstimate,
    ImprovementEvidence,
    ImprovementFinish,
    ImprovementFinished,
    ImprovementRead,
    ImprovementSelection,
    ImprovementStart,
    ImprovementTarget,
    KnowledgeCheckConsent,
    KnowledgeCheckEstimate,
    KnowledgeCheckTarget,
    SelectionConsent,
    SelectionEstimate,
)

router = APIRouter(prefix="/agents/{agent_id}/improvements")


@router.post("/{run_id}/knowledge/estimate", response_model=KnowledgeCheckEstimate)
async def estimate_knowledge_check(
    agent_id: UUID, run_id: UUID, data: KnowledgeCheckTarget, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Estimate draft B against agent changes A on independent questions selected for the topic.

    Context checks assume search finds the passage; they do not verify its facts.
    Source questions and training cases are excluded. No resources are created.
    """
    return await service.estimate_knowledge(ctx, agent_id, run_id, data)


@router.post("/{run_id}/knowledge", response_model=EvalRunRead, status_code=status.HTTP_201_CREATED)
async def start_knowledge_check(
    agent_id: UUID, run_id: UUID, data: KnowledgeCheckConsent, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Check a draft only after consent to its current hash and complete estimated cost.

    Never adds it to a knowledge base. A person must verify the draft's facts.
    """
    return await service.start_knowledge(ctx, agent_id, run_id, data)


@router.post("/estimate", response_model=ImprovementEstimate)
async def estimate_improvement(
    agent_id: UUID, data: ImprovementTarget, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Estimate the complete session, including both eval sides and confirming reruns."""
    return await service.estimate(ctx, agent_id, data)


@router.post("", response_model=ImprovementRead, status_code=status.HTTP_201_CREATED)
async def start_improvement(
    agent_id: UUID, data: ImprovementStart, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Queue a session; 409 names an already active session, 402 refuses its budget."""
    return await service.start(ctx, agent_id, data)


@router.get("", response_model=list[ImprovementRead])
async def list_improvements(agent_id: UUID, service: ImprovementSvc, ctx: Auth) -> Any:
    """Recent sessions, with evidence-free progress visible to readers of the agent."""
    return await service.list_for_agent(ctx, agent_id)


@router.get("/preview", response_model=ImprovementEvidence)
async def preview_improvement_evidence(
    agent_id: UUID, service: ImprovementSvc, ctx: Auth, dataset_id: UUID | None = None
) -> Any:
    """Read a bounded source preview without spending or starting a session."""
    return await service.evidence(ctx, agent_id, dataset_id=dataset_id)


@router.get("/{run_id}/evidence", response_model=ImprovementEvidence)
async def read_improvement_evidence(
    agent_id: UUID, run_id: UUID, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Current-readable examples from the session's frozen inputs and recorded causes."""
    return await service.evidence(ctx, agent_id, run_id=run_id)


@router.get("/{run_id}", response_model=ImprovementRead)
async def read_improvement(agent_id: UUID, run_id: UUID, service: ImprovementSvc, ctx: Auth) -> Any:
    """The session's durable timeline, costs, verdicts and stop reason."""
    return await service.read(ctx, agent_id, run_id)


@router.post("/{run_id}/cancel", response_model=ImprovementRead)
async def stop_improvement(agent_id: UUID, run_id: UUID, service: ImprovementSvc, ctx: Auth) -> Any:
    """Stop new work and cancel children, as the creator or an organization administrator."""
    return await service.cancel(ctx, agent_id, run_id)


@router.post("/{run_id}/rounds/{number}/selection/estimate", response_model=SelectionEstimate)
async def estimate_selection(
    agent_id: UUID,
    run_id: UUID,
    number: int,
    data: ImprovementSelection,
    service: ImprovementSvc,
    ctx: Auth,
) -> Any:
    """Quote a selected subset against the same pinned baseline, including repeats."""
    return await service.estimate_selection(ctx, agent_id, run_id, number, data)


@router.post("/{run_id}/rounds/{number}/selection", response_model=ImprovementRead)
async def check_selection(
    agent_id: UUID,
    run_id: UUID,
    number: int,
    data: SelectionConsent,
    service: ImprovementSvc,
    ctx: Auth,
) -> Any:
    """Recheck only explicitly confirmed changes; keep earlier checks and their costs."""
    return await service.check_selection(ctx, agent_id, run_id, number, data)


@router.post("/{run_id}/rounds/{number}/select", response_model=ImprovementRead)
async def select_improvement_round(
    agent_id: UUID, run_id: UUID, number: int, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Show a measured round for a human decision, after rechecking access and base pins."""
    return await service.select_round(ctx, agent_id, run_id, number)


@router.post("/{run_id}/rounds/{number}/attribution/estimate", response_model=AttributionEstimate)
async def estimate_improvement_attribution(
    agent_id: UUID, run_id: UUID, number: int, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Estimate isolated paired checks for each change without starting paid work."""
    return await service.estimate_attribution(ctx, agent_id, run_id, number)


@router.post("/{run_id}/rounds/{number}/attribution", response_model=ImprovementRead)
async def start_improvement_attribution(
    agent_id: UUID,
    run_id: UUID,
    number: int,
    data: AttributionConsent,
    service: ImprovementSvc,
    ctx: Auth,
) -> Any:
    """Run isolated checks only with explicit consent to the current full estimate."""
    return await service.start_attribution(ctx, agent_id, run_id, number, data)


@router.post("/{run_id}/retry", response_model=ImprovementRead)
async def retry_improvement(
    agent_id: UUID, run_id: UUID, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Explicitly retry a failed paid child, within the original session budget."""
    return await service.retry(ctx, agent_id, run_id)


@router.post("/{run_id}/finish", response_model=ImprovementFinished)
async def finish_improvement(
    agent_id: UUID, run_id: UUID, data: ImprovementFinish, service: ImprovementSvc, ctx: Auth
) -> Any:
    """Accept the checked round and optionally publish after explicit human confirmation."""
    return await service.finish(ctx, agent_id, run_id, data)
