"""Who reads an agent's proposed change to a skill, against a real database (#2422).

A proposal carries the full body an agent wrote, so it is listed and read only by
somebody who could decide it: a caller who may edit the skill it targets. Two
Members each hold `skills:edit` for their own skills only. Each sees and reads the
proposal for their own skill, is told the other's is missing, and an edit grant on
the other's skill widens that - the rule `resolve_access` applies everywhere else.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import ROLE_PERMS, OrgRoleName, Perm, Scope
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel
from app.db.models.skill_proposal import SkillProposal
from app.db.models.user import User
from app.repositories import resource_grant_repo, skill_proposal_repo, skill_repo
from app.schemas.resource_usage import ProposalDecision
from app.services.access import SKILL
from app.services.skill_proposal import SkillProposalService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _member(db: AsyncSession, org: Organization) -> User:
    person = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=person.id, role=OrgRoleName.MEMBER))
    await db.flush()
    return person


async def _proposal_for_skill_of(
    db: AsyncSession, org: Organization, owner: User | None, name: str
) -> SkillProposal:
    skill = None
    if owner is not None:
        skill = await skill_repo.create(
            db,
            organization_id=org.id,
            owner_user_id=owner.id,
            name=name,
            description="A private skill.",
            content="Do it this way.",
        )
    return await skill_proposal_repo.create(
        db,
        organization_id=org.id,
        skill_id=None if skill is None else skill.id,
        agent_id=None,
        conversation_id=None,
        name=name,
        description="Proposed.",
        content="Do it the new way.",
        resources={},
        base_version=None if skill is None else skill.version,
        base_version_id=None if skill is None else skill.latest_version_id,
        fork_id=None,
    )


async def test_a_member_lists_and_reads_only_proposals_they_may_decide(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Evidence access is separate from the resource grants this test narrows.
    monkeypatch.setitem(
        ROLE_PERMS,
        OrgRoleName.MEMBER,
        {**ROLE_PERMS[OrgRoleName.MEMBER], Perm.RUNS_VIEW: Scope.ALL},
    )
    org = await make_org(db, owner=await make_user(db))
    ada, bo = await _member(db, org), await _member(db, org)
    adas = await _proposal_for_skill_of(db, org, ada, f"ada-{uuid.uuid4().hex[:6]}")
    bos = await _proposal_for_skill_of(db, org, bo, f"bo-{uuid.uuid4().hex[:6]}")
    new = await _proposal_for_skill_of(db, org, None, f"new-{uuid.uuid4().hex[:6]}")
    service = SkillProposalService(db)
    ada_ctx = ctx_for(ada, org, OrgRoleName.MEMBER)
    bo_ctx = ctx_for(bo, org, OrgRoleName.MEMBER)

    assert {p.id for p in await service.list_proposals(ada_ctx)} == {adas.id, new.id}
    assert {p.id for p in await service.list_proposals(bo_ctx)} == {bos.id, new.id}
    assert (await service.get(ada_ctx, adas.id)).id == adas.id
    with pytest.raises(NotFoundError) as refused:
        await service.get(ada_ctx, bos.id)
    with pytest.raises(NotFoundError) as missing:
        await service.get(ada_ctx, uuid.uuid4())
    assert refused.value.message == missing.value.message
    with pytest.raises(NotFoundError):
        await service.discard(ada_ctx, bos.id, ProposalDecision(revision=bos.revision))

    assert bos.skill_id is not None
    await resource_grant_repo.upsert(
        db,
        organization_id=org.id,
        subject_user_id=ada.id,
        resource_type=SKILL.key,
        resource_id=bos.skill_id,
        level=GrantLevel.EDIT,
    )

    assert {p.id for p in await service.list_proposals(ada_ctx)} == {adas.id, bos.id, new.id}
    assert (await service.get(ada_ctx, bos.id)).id == bos.id
