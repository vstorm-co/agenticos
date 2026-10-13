"""`CaseGenerationService` - draft cases for a dataset, and decide what was drafted.

Propose, never write: the generator's drafts wait as proposals, and only a
person's Accept turns them into cases - all of one decision into one new dataset
version. Every route lands here, and every one needs `datasets:edit` on the
dataset: a proposal drafted from a conversation is text the caller's dataset
viewers have not been shown, and deciding it changes the dataset.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.case_generation import CaseGeneration, CaseProposal, GenerationStatus
from app.repositories import case_generation_repo
from app.schemas.case_generation import (
    CaseGenerationList,
    CaseGenerationRead,
    CaseProposalAccept,
    CaseProposalDismiss,
    CaseProposalList,
    CaseProposalRead,
)
from app.schemas.dataset import DatasetCaseContent, DatasetVersionRead
from app.services.dataset import DatasetService, GeneratedCase

# A generation runs in the process that answered the request, so a restart loses
# it mid-run. Longer than any generator run takes, it is reported as interrupted
# rather than left spinning.
INTERRUPTED_AFTER = timedelta(minutes=30)
INTERRUPTED = "The generation was interrupted before it finished. Start it again."


def _generation_read(generation: CaseGeneration, *, now: datetime) -> CaseGenerationRead:
    read = CaseGenerationRead.model_validate(generation)
    if (
        generation.status == GenerationStatus.RUNNING.value
        and now - generation.created_at > INTERRUPTED_AFTER
    ):
        return read.model_copy(
            update={"status": GenerationStatus.FAILED.value, "error": INTERRUPTED}
        )
    return read


def _drafted(proposal: CaseProposal) -> DatasetCaseContent:
    return DatasetCaseContent.model_validate(
        {field: getattr(proposal, field) for field in DatasetCaseContent.model_fields}
    )


class CaseGenerationService:
    """Generate cases for a dataset and decide what was generated."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.datasets = DatasetService(db)

    async def list_generations(
        self, ctx: AuthContext, dataset_id: UUID, *, limit: int = 20
    ) -> CaseGenerationList:
        """The dataset's newest generations, with how each went."""
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        generations = await case_generation_repo.list_generations(
            self.db, dataset.id, organization_id=ctx.organization_id, limit=limit
        )
        now = datetime.now(UTC)
        return CaseGenerationList(items=[_generation_read(g, now=now) for g in generations])

    async def list_proposals(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        *,
        generation_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> CaseProposalList:
        """A page of the drafted cases waiting on this dataset."""
        dataset = await self.datasets.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        items, total = await case_generation_repo.list_proposals(
            self.db,
            dataset.id,
            organization_id=ctx.organization_id,
            generation_id=generation_id,
            skip=skip,
            limit=limit,
        )
        return CaseProposalList(
            items=[CaseProposalRead.model_validate(item) for item in items], total=total
        )

    async def _take(
        self, ctx: AuthContext, dataset_id: UUID, ids: list[UUID]
    ) -> list[CaseProposal]:
        """Take proposals out of the queue under the dataset's lock.

        Raises:
            NotFoundError: When none of them is waiting any more - somebody else
                decided them first, or they never were this dataset's.
        """
        taken = await case_generation_repo.take_proposals(
            self.db, dataset_id, ids, organization_id=ctx.organization_id
        )
        if not taken:
            raise NotFoundError(
                message="These proposed cases were already decided",
                details={"dataset_id": dataset_id, "ids": ids},
            )
        return taken

    async def _count(self, ctx: AuthContext, taken: list[CaseProposal], *, accepted: bool) -> None:
        per_generation = Counter(proposal.generation_id for proposal in taken)
        await case_generation_repo.count_decisions(
            self.db, dict(per_generation), organization_id=ctx.organization_id, accepted=accepted
        )

    async def accept(
        self, ctx: AuthContext, dataset_id: UUID, data: CaseProposalAccept
    ) -> DatasetVersionRead:
        """Accept drafted cases - as drafted, or as edited - into one new dataset version.

        A proposal somebody else decided meanwhile is skipped; the version holds
        the ones this decision took.

        Raises:
            NotFoundError: For a dataset the caller may not edit, or when none of
                the proposals is still waiting.
        """
        dataset = await self.datasets.lock_for_edit(ctx, dataset_id)
        edits = {item.id: item.content for item in data.items}
        taken = await self._take(ctx, dataset.id, list(edits))
        cases = [
            GeneratedCase(
                content=edits[proposal.id] or _drafted(proposal),
                source_document_id=proposal.source_document_id,
                source_run_id=proposal.source_run_id,
                source_conversation_id=proposal.source_conversation_id,
                source_message_id=proposal.source_message_id,
            )
            for proposal in taken
        ]
        version = await self.datasets.add_generated(ctx, dataset, cases)
        await self._count(ctx, taken, accepted=True)
        return version

    async def dismiss(self, ctx: AuthContext, dataset_id: UUID, data: CaseProposalDismiss) -> None:
        """Dismiss drafted cases. Nothing of them is kept, and the dataset does not change.

        Raises:
            NotFoundError: For a dataset the caller may not edit, or when none of
                the proposals is still waiting.
        """
        dataset = await self.datasets.lock_for_edit(ctx, dataset_id)
        taken = await self._take(ctx, dataset.id, data.ids)
        await self._count(ctx, taken, accepted=False)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.proposals_dismissed",
            target_type="dataset",
            target_id=str(dataset.id),
            details={"name": dataset.name, "dismissed": len(taken)},
        )
