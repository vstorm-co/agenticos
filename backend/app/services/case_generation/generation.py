"""One generation, run after the request that started it has answered.

The generator is a system agent, so it runs through `SystemAgentRunner` as the
person who asked - which checks the organization's AI switch, the agent's state
and the caller's `agents:run` again here, because any of them may have changed
between the request and this run. Every way it can end is recorded on the
generation: `ready` with its drafts, or `failed` with a reason this platform
wrote and, when there was one, the run to open in Activity.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.system_agents import CASE_GENERATOR
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.models.case_generation import CaseOrigin, CaseProposal, GenerationStatus
from app.db.session import get_db_context
from app.repositories import case_generation_repo
from app.services.case_generation.drafts import DraftedCases, keep
from app.services.case_generation.sources import Material
from app.services.dataset import redacted_case
from app.services.system_agent_runner import SystemAgentRunner

logger = logging.getLogger(__name__)

FAILED = "The generation failed. Try again, or open the generator's run in Activity."
NOTHING_KEPT = (
    "The generator drafted nothing that cites what it was shown. Try again, or ask for fewer cases."
)
_ERROR_LIMIT = 500


async def run_generation(
    *,
    generation_id: UUID,
    ctx: AuthContext,
    prompt: str,
    material: Material,
    quotas: dict[CaseOrigin, int],
) -> None:
    """Run one generation on a session of its own. Started after the request commits."""
    async with get_db_context() as db:
        await generate(
            db,
            generation_id=generation_id,
            ctx=ctx,
            prompt=prompt,
            material=material,
            quotas=quotas,
        )


async def _finish(
    db: AsyncSession,
    generation_id: UUID,
    ctx: AuthContext,
    *,
    status: GenerationStatus,
    error: str | None = None,
    run_id: UUID | None = None,
    proposed: int = 0,
) -> None:
    generation = await case_generation_repo.get_generation(
        db, generation_id, organization_id=ctx.organization_id
    )
    if generation is None:
        # The dataset, and its generations with it, was deleted while this ran.
        return
    await case_generation_repo.finish_generation(
        db,
        generation,
        status=status.value,
        finished_at=datetime.now(UTC),
        error=error[:_ERROR_LIMIT] if error else None,
        run_id=run_id,
        proposed_count=proposed,
    )


async def generate(
    db: AsyncSession,
    *,
    generation_id: UUID,
    ctx: AuthContext,
    prompt: str,
    material: Material,
    quotas: dict[CaseOrigin, int],
) -> None:
    """Run the generator once and record what it drafted. Never raises.

    The drafts that keep their source's rule become proposals, redacted like any
    case on its way in; the rest are counted in the log and nowhere else. A
    failure rolls the session back before recording itself: the generation was
    committed by the request and the run by the runner, so nothing of theirs is
    lost, and a database error may have left the transaction unusable.
    """
    try:
        result = await SystemAgentRunner(db).run(
            ctx, key=CASE_GENERATOR.key, prompt=prompt, output_type=DraftedCases
        )
    except AppException as exc:
        await db.rollback()
        await _finish(
            db,
            generation_id,
            ctx,
            status=GenerationStatus.FAILED,
            error=exc.message,
            run_id=getattr(exc, "run_id", None),
        )
        return
    except Exception:
        logger.exception("case_generation_failed", extra={"generation_id": str(generation_id)})
        await db.rollback()
        await _finish(db, generation_id, ctx, status=GenerationStatus.FAILED, error=FAILED)
        return

    generation = await case_generation_repo.get_generation(
        db, generation_id, organization_id=ctx.organization_id
    )
    if generation is None:
        return
    drafts, dropped = keep(result.output, material, quotas=quotas)
    proposals: list[CaseProposal] = []
    for position, draft in enumerate(drafts):
        fields, _ = redacted_case(draft.case.content)
        proposals.append(
            CaseProposal(
                organization_id=ctx.organization_id,
                generation_id=generation_id,
                dataset_id=generation.dataset_id,
                position=position,
                origin=draft.origin.value,
                source_document_id=draft.case.source_document_id,
                source_run_id=draft.case.source_run_id,
                source_conversation_id=draft.case.source_conversation_id,
                source_message_id=draft.case.source_message_id,
                **fields,
            )
        )
    logger.info(
        "case_generation_drafted",
        extra={
            "generation_id": str(generation_id),
            "kept": len(proposals),
            "dropped": dropped,
        },
    )
    if not proposals:
        await _finish(
            db,
            generation_id,
            ctx,
            status=GenerationStatus.FAILED,
            error=NOTHING_KEPT,
            run_id=result.run.id,
        )
        return
    await case_generation_repo.add_proposals(db, proposals)
    await _finish(
        db,
        generation_id,
        ctx,
        status=GenerationStatus.READY,
        run_id=result.run.id,
        proposed=len(proposals),
    )
