"""Whoever may read a proposed skill change is whoever may decide it.

A Member edits only the skills they own or were granted, so the changes proposed
for anybody else's skill are neither listed nor opened for them - nor discarded
- and a grant on that skill widens all three at once. A change for a skill nobody
has written yet is one anybody who may create skills could accept.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.db.models.skill import Skill
from app.db.models.skill_proposal import SkillProposal
from app.schemas.resource_usage import ProposalDecision
from app.services.skill_proposal import SkillProposalService
from tests.integration.test_authoring import _member, _owner

pytestmark = pytest.mark.anyio


async def _skill_with_change(db: AsyncSession, owner: AuthContext, name: str) -> SkillProposal:
    skill = Skill(
        organization_id=owner.organization_id,
        owner_user_id=owner.user_id,
        visibility="private",
        name=name,
        description="d",
        content="c",
    )
    db.add(skill)
    await db.flush()
    proposal = SkillProposal(
        organization_id=owner.organization_id,
        skill_id=skill.id,
        name=name,
        description="d",
        content="Proposed.",
        resources={},
    )
    db.add(proposal)
    await db.flush()
    return proposal


@pytest.mark.security
async def test_each_member_reads_and_decides_only_the_changes_to_skills_they_may_edit(db):
    owner = await _owner(db)
    ann = await _member(db, owner, OrgRoleName.MEMBER)
    bob = await _member(db, owner, OrgRoleName.MEMBER)
    anns = await _skill_with_change(db, ann, "anns-skill")
    bobs = await _skill_with_change(db, bob, "bobs-skill")
    brand_new = SkillProposal(
        organization_id=owner.organization_id,
        skill_id=None,
        name="brand-new",
        description="d",
        content="New.",
        resources={},
    )
    db.add(brand_new)
    await db.flush()
    service = SkillProposalService(db)

    assert sorted(item.name for item in await service.list_read(ann)) == [
        "anns-skill",
        "brand-new",
    ]
    assert (await service.read(ann, anns.id)).name == "anns-skill"
    with pytest.raises(NotFoundError, match="Skill change not found"):
        await service.read(ann, bobs.id)
    with pytest.raises(NotFoundError, match="Skill change not found"):
        await service.discard(ann, bobs.id, ProposalDecision(revision=1))
    with pytest.raises(NotFoundError, match="Skill change not found"):
        await service.read(ann, uuid.uuid4())

    # A grant on Bob's skill lets Ann decide its change, as it lets her edit the skill.
    db.add(
        ResourceGrant(
            organization_id=owner.organization_id,
            subject_user_id=ann.user_id,
            resource_type="skill",
            resource_id=bobs.skill_id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()

    assert sorted(item.name for item in await service.list_read(ann)) == [
        "anns-skill",
        "bobs-skill",
        "brand-new",
    ]
    discarded = await service.discard(ann, bobs.id, ProposalDecision(revision=1))
    assert discarded.status == "discarded"
    assert sorted(item.name for item in await service.list_read(bob)) == [
        "bobs-skill",
        "brand-new",
    ]
