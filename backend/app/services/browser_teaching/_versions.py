"""Copy reviewed procedure provenance only with its exact proposal body."""

from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.browser_teaching import BrowserProcedure, TeachingReason, TeachingRefused
from app.db.models.skill_proposal import ProposalStatus
from app.db.models.skill_version import SkillVersionSource
from app.repositories import skill_proposal as proposal_repo


async def procedure_for_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    skill_id: UUID,
    source: SkillVersionSource,
    proposal_id: UUID | None,
    content: str,
    description: str,
) -> dict[str, JsonValue] | None:
    """Ordinary edits lose the annotation; a teaching apply keeps reviewed facts.

    A checked fork is written before its existing decision marks the proposal
    applied in the same transaction. Discovery separately requires APPLIED and
    the exact saved version, so a pending proposal is never discoverable.
    """
    if source is not SkillVersionSource.BROWSER_TEACHING:
        return None
    proposal = (
        None
        if proposal_id is None
        else await proposal_repo.get(db, proposal_id, organization_id=organization_id)
    )
    if (
        proposal is None
        or proposal.source != SkillVersionSource.BROWSER_TEACHING.value
        or proposal.status not in {ProposalStatus.PENDING.value, ProposalStatus.APPLIED.value}
        or proposal.skill_id not in {None, skill_id}
        or proposal.content != content
        or proposal.description != description
        or proposal.browser_procedure is None
    ):
        raise TeachingRefused(TeachingReason.INVALID_DRAFT)
    try:
        procedure = BrowserProcedure.model_validate(proposal.browser_procedure)
    except ValidationError:
        raise TeachingRefused(TeachingReason.INVALID_DRAFT) from None
    return procedure.model_dump(mode="json")
