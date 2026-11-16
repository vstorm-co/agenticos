"""Materialize an applied failure-learning proposal into its existing skill.

The service resolves a persisted proposal within its organization and agent,
checks that it is an applied skill proposal with consistent content hashes,
and verifies the request against that row. It writes through `SkillService`;
audit provenance comes from the proposal and its linked ledger entry, never
from caller-asserted identifiers or hashes.
"""

import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.skill import Skill
from app.repositories import failure_learning as failure_learning_repo
from app.schemas.auto_skill_learning import LearnedSkillRead, LearnSkillCreate
from app.schemas.skill import SkillUpdate
from app.services.agent_registry import AgentRegistryService
from app.services.skills import SkillService


def _sha256(content: str) -> str:
    """The content hash, the same digest #32 records as its base."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class AutoSkillLearningService:
    """Materialise approved skill-target proposals as catalog skills."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)
        self.skills = SkillService(db)

    async def learn(
        self, ctx: AuthContext, agent_id: UUID, data: LearnSkillCreate
    ) -> LearnedSkillRead:
        """Learn one applied proposal for its existing skill.

        The proposal is loaded for this organization and agent. Only an
        applied skill proposal may be learned, and the submitted content,
        target, and provenance must match the stored row. Audit provenance
        comes from that row and its linked ledger entry.

        Raises:
            NotFoundError: The agent, proposal, or named skill is out of reach,
                or the proposal is not an applied skill proposal.
            ConflictError: The submitted data does not match the proposal, or
                the named skill no longer matches the proposal's content.
        """
        await self.registry.get(ctx, agent_id, perm=Perm.AGENTS_VIEW)
        proposal = await failure_learning_repo.get_proposal(
            self.db,
            data.proposal_id,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
        )
        if (
            proposal is None
            or proposal.status != "applied"
            or proposal.target_type != "skill"
            or proposal.skill_id is None
            or proposal.reverted_at is not None
        ):
            raise NotFoundError(
                message="Applied skill proposal not found",
                details={"proposal_id": str(data.proposal_id)},
            )
        new_hash = _sha256(proposal.new_text)
        if proposal.applied_content_sha256 != new_hash:
            raise ConflictError(
                message="The applied proposal content is inconsistent",
                details={"proposal_id": str(proposal.id)},
            )
        if (
            (data.skill_id is not None and data.skill_id != proposal.skill_id)
            or data.content != proposal.new_text
            or (data.rationale is not None and data.rationale != proposal.rationale)
            or (
                data.ledger_entry_id is not None
                and data.ledger_entry_id != proposal.ledger_entry_id
            )
            or (
                data.base_content_sha256 is not None
                and data.base_content_sha256 != proposal.base_content_sha256
            )
        ):
            raise ConflictError(
                message="The submitted learning data does not match the applied proposal",
                details={"proposal_id": str(proposal.id)},
            )
        pattern_key = None
        if proposal.ledger_entry_id is not None:
            entry = await failure_learning_repo.get_entry(
                self.db,
                proposal.ledger_entry_id,
                organization_id=ctx.organization_id,
                agent_id=agent_id,
            )
            if entry is not None:
                pattern_key = entry.pattern_key
        verified_data = data.model_copy(
            update={
                "proposal_id": proposal.id,
                "skill_id": proposal.skill_id,
                "content": proposal.new_text,
                "rationale": proposal.rationale,
                "ledger_entry_id": proposal.ledger_entry_id,
                "pattern_key": pattern_key,
                "base_content_sha256": proposal.base_content_sha256,
            }
        )
        skill = await self.skills.get(ctx, proposal.skill_id, perm=Perm.SKILLS_EDIT)
        return await self._learn_into_existing(ctx, skill, verified_data, new_hash)

    async def _learn_into_existing(
        self, ctx: AuthContext, skill: Skill, data: LearnSkillCreate, new_hash: str
    ) -> LearnedSkillRead:
        """The proposal edits a skill that already exists."""
        current_hash = _sha256(skill.content)
        if current_hash == new_hash:
            return self._read(skill, data, created=False, already_learned=True)
        if data.base_content_sha256 is not None and current_hash == data.base_content_sha256:
            updated = await self.skills.update(ctx, skill.id, SkillUpdate(content=data.content))
            await self._audit(ctx, updated, data, new_hash, created=False)
            return self._read(updated, data, created=False, already_learned=False)
        raise ConflictError(
            message="The skill has changed since this proposal was written - "
            "re-base the proposal instead",
            details={
                "proposal_id": str(data.proposal_id),
                "skill_id": str(skill.id),
                "base_content_sha256": data.base_content_sha256,
            },
        )

    async def _audit(
        self,
        ctx: AuthContext,
        skill: Skill,
        data: LearnSkillCreate,
        new_hash: str,
        *,
        created: bool,
    ) -> None:
        """The provenance record: which proposal, which failures, which text."""
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.learned",
            target_type="skill",
            target_id=str(skill.id),
            details={
                "proposal_id": str(data.proposal_id),
                "ledger_entry_id": str(data.ledger_entry_id)
                if data.ledger_entry_id is not None
                else None,
                "pattern_key": data.pattern_key,
                "created": created,
                "version": skill.version,
                "content_sha256": new_hash,
                "base_content_sha256": data.base_content_sha256,
                "rationale": data.rationale,
            },
        )

    @staticmethod
    def _read(
        skill: Skill, data: LearnSkillCreate, *, created: bool, already_learned: bool
    ) -> LearnedSkillRead:
        return LearnedSkillRead(
            skill_id=skill.id,
            name=skill.name,
            version=skill.version,
            content_sha256=_sha256(skill.content),
            created=created,
            already_learned=already_learned,
            proposal_id=data.proposal_id,
            ledger_entry_id=data.ledger_entry_id,
            pattern_key=data.pattern_key,
        )
