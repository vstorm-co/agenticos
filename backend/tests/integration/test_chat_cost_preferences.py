"""Chat price choices are membership scoped and constrained in PostgreSQL."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chat_costs import ChatCostVisibility
from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.schemas.console_experience import ConsoleExperienceUpdate
from app.services.console_experience import ConsoleExperienceService

pytestmark = pytest.mark.anyio


async def test_preference_isolation_ceiling_and_reset(db: AsyncSession) -> None:
    user = User(id=uuid4(), email="cost-preference@example.com", is_active=True)
    db.add(user)
    await db.flush()
    first = Organization(id=uuid4(), name="First", slug="cost-first", created_by_user_id=user.id)
    other = Organization(id=uuid4(), name="Other", slug="cost-other", created_by_user_id=user.id)
    db.add_all([first, other])
    await db.flush()
    db.add_all(
        [
            OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")
            for org in (first, other)
        ]
    )
    await db.flush()
    service = ConsoleExperienceService(db)
    ctx = AuthContext(user_id=user.id, organization_id=first.id, role="owner")
    second = AuthContext(user_id=user.id, organization_id=other.id, role="owner")
    assert (
        await service.update(ctx, ConsoleExperienceUpdate(chat_costs=False))
    ).costs.preference is False
    assert (await service.read(second)).costs.effective
    await organization_repo.set_chat_cost_visibility(db, first, policy=ChatCostVisibility.NOBODY)
    assert not (await service.update(ctx, ConsoleExperienceUpdate(chat_costs=True))).costs.effective
    await organization_repo.set_chat_cost_visibility(db, first, policy=None)
    assert (await service.update(ctx, ConsoleExperienceUpdate(chat_costs=None))).costs.effective
    await deployment_settings_repo.upsert(db, update_data={"chat_costs_available": False})
    assert not (await service.read(second)).costs.effective
    assert (
        await member_repo.set_chat_cost_preference(
            db, organization_id=uuid4(), user_id=user.id, visible=True
        )
        is None
    )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            first.chat_cost_visibility = "typo"
            await db.flush()
