"""One generation, run by its job after the request that started it has answered.

The generator is a system agent, so it runs through `SystemAgentRunner` as the
person who asked - which checks the organization's AI switch, the agent's state
and the caller's `agents:run` again here, because any of them may have changed
between the request and this run. Every way it can end is recorded on the
generation: `ready` with its drafts, or `failed` with a reason this platform
wrote and, when there was one, the run to open in Activity.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.system_agents import CASE_GENERATOR
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.case_generation import CaseOrigin, CaseProposal, GenerationStatus
from app.repositories import case_generation_repo, user_repo
from app.services.case_generation.drafts import Draft, DraftedCases, keep
from app.services.case_generation.sources import Material
from app.services.dataset import redacted_case
from app.services.system_agent_runner import SystemAgentResult, SystemAgentRunner

logger = logging.getLogger(__name__)

FAILED = "The generation failed. Try again, or open the generator's run in Activity."
NOTHING_KEPT = (
    "The generator drafted nothing that cites what it was shown. Try again, or ask for fewer cases."
)
_ERROR_LIMIT = 500


async def finish(
    db: AsyncSession,
    generation_id: UUID,
    ctx: AuthContext,
    *,
    status: GenerationStatus,
    error: str | None = None,
    run_id: UUID | None = None,
    proposed: int = 0,
    unreadable: int = 0,
    rejected: int = 0,
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
        unreadable_count=unreadable,
        rejected_count=rejected,
    )


async def generate(
    db: AsyncSession,
    *,
    generation_id: UUID,
    ctx: AuthContext,
    prompt: str,
    material: Material,
    quotas: dict[CaseOrigin, int],
    generator_agent_id: UUID | None = None,
) -> None:
    """Run the generator once and record what it drafted. Never raises.

    The drafts that keep their source's rule become proposals, redacted like any
    case on its way in; the rest are counted on the generation - the cases that
    could not be read apart from the ones that broke a rule - and why in the log. A
    refusal of this platform's own leaves the session as it is, so what the
    runner wrote on the run - why its answer could not be read - is kept. Any
    other failure rolls the session back before recording itself: the generation
    was committed by the request and the run by the runner, so nothing of theirs
    is lost, and a database error - a source deleted while the generator ran -
    may have left the transaction unusable.
    """
    try:
        result = await SystemAgentRunner(db).run(
            ctx,
            key=CASE_GENERATOR.key,
            agent_id=generator_agent_id,
            prompt=prompt,
            output_type=DraftedCases,
            knowledge_base_ids=material.knowledge_base_ids,
        )
    except AppException as exc:
        await finish(
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
        await finish(db, generation_id, ctx, status=GenerationStatus.FAILED, error=FAILED)
        return

    # Read before a rollback expires the row it is on.
    run_id = result.run.id
    try:
        await _record(db, generation_id, ctx, result=result, material=material, quotas=quotas)
    except Exception:
        logger.exception("case_generation_failed", extra={"generation_id": str(generation_id)})
        await db.rollback()
        await finish(
            db, generation_id, ctx, status=GenerationStatus.FAILED, error=FAILED, run_id=run_id
        )


async def _still_asked(db: AsyncSession, drafts: list[Draft], material: Material) -> list[Draft]:
    """The drafts whose askers still have an account, with each asker's erasure held off.

    The generator ran for minutes after the questions were read. An erasure in
    that time purged the drafts that existed then, and the chats, messages and
    runs these come from outlive the account with no link back to it - so a
    draft written now from a deleted person's question would be found by no
    later purge. The lock is the one the purge holds to its commit, taken in one
    order and before reading the accounts, and held to this commit: an erasure
    either finished first, and its person's drafts are dropped here, or waits and
    removes them.
    """
    askers = {question.message_id: question.askers for question in material.questions}

    def of(draft: Draft) -> tuple[UUID, ...]:
        message_id = draft.case.source_message_id
        return () if message_id is None else askers.get(message_id, ())

    people = sorted({person for draft in drafts for person in of(draft)})
    for person in people:
        await hold_subject(db, LockScope.PERSONAL_DATA_PER_USER, person)
    present = await user_repo.existing_ids(db, people)
    return [draft for draft in drafts if set(of(draft)) <= present]


async def _record(
    db: AsyncSession,
    generation_id: UUID,
    ctx: AuthContext,
    *,
    result: SystemAgentResult[DraftedCases],
    material: Material,
    quotas: dict[CaseOrigin, int],
) -> None:
    generation = await case_generation_repo.get_generation(
        db, generation_id, organization_id=ctx.organization_id
    )
    if generation is None:
        return
    drafts, dropped = keep(result.output, material, quotas=quotas)
    kept = await _still_asked(db, drafts, material)
    dropped += len(drafts) - len(kept)
    drafts = kept
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
            "unreadable": result.output.unreadable,
        },
    )
    if not proposals:
        await finish(
            db,
            generation_id,
            ctx,
            status=GenerationStatus.FAILED,
            error=NOTHING_KEPT,
            run_id=result.run.id,
            unreadable=result.output.unreadable,
            rejected=dropped,
        )
        return
    await case_generation_repo.add_proposals(db, proposals)
    await finish(
        db,
        generation_id,
        ctx,
        status=GenerationStatus.READY,
        run_id=result.run.id,
        proposed=len(proposals),
        unreadable=result.output.unreadable,
        rejected=dropped,
    )
