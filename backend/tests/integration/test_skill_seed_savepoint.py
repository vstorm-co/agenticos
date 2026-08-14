"""The listing's bundled-skill top-up survives losing a race, against Postgres.

`SkillService._ensure_bundled` wraps each install in `begin_nested()` so that a
unique-name violation - two first listings racing to the same missing skill -
costs that one row and never the reader's page. The unit suite asserts the shape
with mocks, which cannot prove the part that matters: after asyncpg raises a
real `IntegrityError`, only a savepoint rollback leaves the session usable for
the installs and the page query that follow. This asks Postgres.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.skill import Skill
from app.db.models.user import User
from app.services import skills as skills_module
from app.services.skills import SkillService

pytestmark = pytest.mark.anyio


async def _org_with_owner(db) -> tuple[Organization, User]:
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(owner)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=owner.id,
            role="owner",
        )
    )
    await db.flush()
    return organization, owner


async def test_a_real_unique_violation_costs_one_row_and_the_page_still_answers(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race, staged for real: the organization already holds a skill carrying
    a bundled skill's name, and both reads that would notice it are blinded -
    `list_names` (the top-up's gap check) and `get_by_name` (create's own
    refusal) - so the install reaches the flush and Postgres raises the actual
    unique violation. The savepoint must confine it: the skills after the loser
    still install, the listing still answers, and the pre-existing row is left
    exactly as it was.
    """
    organization, owner = await _org_with_owner(db)
    existing = Skill(
        id=uuid.uuid4(),
        organization_id=organization.id,
        owner_user_id=owner.id,
        name="code-review",
        description="the organization's own take",
        content="Review the way we review.",
    )
    db.add(existing)
    await db.flush()

    monkeypatch.setattr(skills_module.skill_repo, "list_names", AsyncMock(return_value=set()))
    monkeypatch.setattr(skills_module.skill_repo, "get_by_name", AsyncMock(return_value=None))

    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    listing = await SkillService(db).list_readable(ctx)

    # The colliding install sorts first among the bundled skills, so a dead
    # session would have taken the other two installs and the page with it.
    assert listing.total == 3
    assert {item.name for item in listing.items} == {
        "code-review",
        "incident-report",
        "refund-policy",
    }

    survivors = (await db.execute(select(Skill).where(Skill.name == "code-review"))).scalars().all()
    assert [skill.id for skill in survivors] == [existing.id]
    assert survivors[0].content == "Review the way we review."
    assert (
        await db.scalar(
            select(func.count(Skill.id)).where(Skill.organization_id == organization.id)
        )
    ) == 3
