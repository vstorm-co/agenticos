"""A skill change an agent's workspace wrote applies only onto the version its run was given.

Without that, applying it would silently replace whatever a person wrote into the
skill since - the agent never saw that edit, and the reviewer has no way to tell.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConcurrentChangeError
from app.core.permissions import AuthContext
from app.db.models.skill import Skill
from app.schemas.resource_usage import ProposalDecision
from app.schemas.skill import SkillUpdate
from app.services.skill_proposal import SkillProposalService
from app.services.skill_workspace import SkillChange
from app.services.skills import SkillService
from tests.integration.test_authoring import _clerk, _owner

pytestmark = pytest.mark.anyio


async def _skill(db: AsyncSession, ctx: AuthContext) -> Skill:
    skill = Skill(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        name="refunds",
        description="How refunds work.",
        content="Ask for the order id.",
    )
    db.add(skill)
    await db.flush()
    return skill


def _change(skill: Skill, content: str) -> SkillChange:
    return SkillChange(
        name=skill.name,
        skill_id=skill.id,
        base_version=skill.version,
        description=skill.description,
        content=content,
        resources={},
    )


async def test_a_change_written_before_a_persons_edit_is_refused_and_the_edit_kept(db):
    ctx = await _owner(db)
    agent = await _clerk(db, ctx)
    skill = await _skill(db, ctx)
    service = SkillProposalService(db)
    [proposal] = await service.record(
        ctx, [_change(skill, "Ask for the receipt.")], agent_id=agent.id, conversation_id=None
    )
    assert proposal.base_version == 1

    await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Ask for the invoice."))

    with pytest.raises(ConcurrentChangeError, match="changed since"):
        await service.apply(ctx, proposal.id, ProposalDecision(revision=proposal.revision))
    await db.refresh(skill)
    assert skill.content == "Ask for the invoice."
    assert skill.version == 2


async def test_a_later_run_rewriting_the_proposal_takes_the_version_it_was_given(db):
    ctx = await _owner(db)
    agent = await _clerk(db, ctx)
    skill = await _skill(db, ctx)
    service = SkillProposalService(db)
    [first] = await service.record(
        ctx, [_change(skill, "Ask for the receipt.")], agent_id=agent.id, conversation_id=None
    )
    await SkillService(db).update(ctx, skill.id, SkillUpdate(content="Ask for the invoice."))
    await db.refresh(skill)

    [rewritten] = await service.record(
        ctx,
        [_change(skill, "Ask for the invoice, then the receipt.")],
        agent_id=agent.id,
        conversation_id=None,
    )

    assert rewritten.id == first.id
    assert rewritten.base_version == 2
    applied = await service.apply(ctx, rewritten.id, ProposalDecision(revision=rewritten.revision))
    assert applied.status == "applied"
    await db.refresh(skill)
    assert skill.content == "Ask for the invoice, then the receipt."
