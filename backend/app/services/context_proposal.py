"""Reviewing what the authoring assistant proposed for a context file: apply it, or discard it.

A context file has no draft, so applying a proposal is live: every agent bound
to the file reads the new body on its next run. The reviewer is shown which
agents those are - as far as they may see them - and may check the change with
evals on one of them first.

Applying needs edit access to the file, and refuses once the file changed since
the proposal was written: the reviewer compares the two versions themselves
rather than have somebody's edit thrown away. Both decisions are final.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, ConcurrentChangeError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.db.models.skill_proposal import ProposalStatus
from app.repositories import context_proposal_repo, context_repo
from app.schemas.context import ContextFileUpdate
from app.schemas.context_proposal import ContextProposalList, ContextProposalRead
from app.schemas.resource_usage import AgentUsage
from app.services.access import CONTEXT, accessible_ids
from app.services.context import ContextService
from app.services.resource_usage import agents_using

logger = logging.getLogger(__name__)


class ContextProposalService:
    """List, apply and discard the assistant's proposed context file changes."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.contexts = ContextService(db)

    async def list_read(
        self, ctx: AuthContext, *, status: str | None = None
    ) -> ContextProposalList:
        """The proposals for the files the caller may see, newest first."""
        proposals = await context_proposal_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id, status=status
        )
        files = await context_repo.get_many(
            self.db,
            sorted({proposal.context_id for proposal in proposals}),
            organization_id=ctx.organization_id,
        )
        visible = await accessible_ids(
            self.db, ctx, list(files.values()), Perm.CONTEXT_VIEW, resource_type=CONTEXT
        )
        used = await agents_using(self.db, ctx, field="context_ids", resource_ids=sorted(visible))
        items = [
            self._read(ctx, proposal, files[proposal.context_id], used[proposal.context_id])
            for proposal in proposals
            if proposal.context_id in visible
        ]
        return ContextProposalList(items=items, total=len(items))

    async def read(self, ctx: AuthContext, proposal_id: UUID) -> ContextProposalRead:
        proposal, file = await self._get(ctx, proposal_id)
        used = await agents_using(self.db, ctx, field="context_ids", resource_ids=[file.id])
        return self._read(ctx, proposal, file, used[file.id])

    @staticmethod
    def _read(
        ctx: AuthContext, proposal: ContextProposal, file: ContextFile, used: list[AgentUsage]
    ) -> ContextProposalRead:
        """One proposal as a reviewer reads it - quotes only for a reader of runs."""
        quotes = ctx.has(Perm.RUNS_VIEW)
        return ContextProposalRead(
            id=proposal.id,
            context_id=proposal.context_id,
            context_name=file.name,
            description=proposal.description,
            content=proposal.content,
            current_description=file.description,
            current_content=file.content,
            status=proposal.status,
            decided_by_user_id=proposal.decided_by_user_id,
            decided_at=proposal.decided_at,
            stale=file.updated_at != proposal.base_updated_at,
            rationale=proposal.rationale,
            evidence=[
                {"run_id": item.get("run_id"), "quote": item.get("quote") if quotes else None}
                for item in proposal.evidence
            ],
            evidence_dropped=proposal.evidence_dropped,
            expected_effect=proposal.expected_effect,
            authoring_request_id=proposal.authoring_request_id,
            used_by=used,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
        )

    async def _get(
        self, ctx: AuthContext, proposal_id: UUID, *, perm: Perm = Perm.CONTEXT_VIEW
    ) -> tuple[ContextProposal, ContextFile]:
        """The proposal, and its file - when the caller may reach the file with `perm`.

        Raises:
            NotFoundError: No such proposal in the organization, or the caller may
                not reach its file - which they may not learn exists.
        """
        proposal = await context_proposal_repo.get(
            self.db, proposal_id, organization_id=ctx.organization_id
        )
        if proposal is None:
            raise NotFoundError(
                message="Context change not found", details={"proposal_id": proposal_id}
            )
        file = await self.contexts.get(ctx, proposal.context_id, perm=perm)
        return proposal, file

    @staticmethod
    def _refuse_second_decision(proposal: ContextProposal) -> None:
        if proposal.status != ProposalStatus.PENDING.value:
            raise AlreadyExistsError(
                message=(
                    f"This change was already {proposal.status}. A second decision would "
                    "either apply it twice or overrule whoever decided first."
                ),
                details={"proposal_id": proposal.id, "status": proposal.status},
            )

    async def apply(self, ctx: AuthContext, proposal_id: UUID) -> ContextProposalRead:
        """Write the proposed body to the file, then mark the proposal applied.

        Raises:
            NotFoundError: As :meth:`read`, or the caller may not edit the file.
            AlreadyExistsError: It was already decided.
            ConcurrentChangeError: The file changed since the proposal was written.
        """
        proposal, file = await self._get(ctx, proposal_id, perm=Perm.CONTEXT_EDIT)
        self._refuse_second_decision(proposal)
        # Locking re-reads the row into `file`: an edit committed meanwhile is seen.
        await context_repo.lock(self.db, file.id, organization_id=ctx.organization_id)
        if file.updated_at != proposal.base_updated_at:
            raise ConcurrentChangeError(
                message=(
                    f"'{file.name}' changed since this was proposed. Compare the two and "
                    "edit the file by hand, or ask the assistant again."
                ),
                details={"proposal_id": proposal.id, "context_id": file.id},
            )
        await self.contexts.update(
            ctx,
            file.id,
            ContextFileUpdate(description=proposal.description, content=proposal.content),
        )
        return await self._decide(ctx, proposal, file, ProposalStatus.APPLIED)

    async def discard(self, ctx: AuthContext, proposal_id: UUID) -> ContextProposalRead:
        """Refuse a change, keeping the record of what was proposed."""
        proposal, file = await self._get(ctx, proposal_id, perm=Perm.CONTEXT_EDIT)
        self._refuse_second_decision(proposal)
        return await self._decide(ctx, proposal, file, ProposalStatus.DISCARDED)

    async def _decide(
        self,
        ctx: AuthContext,
        proposal: ContextProposal,
        file: ContextFile,
        status: ProposalStatus,
    ) -> ContextProposalRead:
        decided = await context_proposal_repo.decide(
            self.db, proposal=proposal, status=status, decided_by=ctx.subject_id
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=f"context.change_{status.value}",
            target_type="context",
            target_id=str(file.id),
            details={"name": file.name, "proposal_id": str(proposal.id)},
        )
        used = await agents_using(self.db, ctx, field="context_ids", resource_ids=[file.id])
        return self._read(ctx, decided, file, used[file.id])
