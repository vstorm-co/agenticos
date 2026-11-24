"""Real membership isolation and the new bounded goal constraint."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import member_repo, onboarding_repo
from app.schemas.onboarding import OnboardingUpdate

pytestmark = pytest.mark.anyio


async def test_a_goal_is_scoped_to_both_person_and_organization(db: AsyncSession) -> None:
    people = [
        User(id=uuid4(), email=f"{uuid4().hex}@example.com", is_active=True) for _ in range(2)
    ]
    db.add_all(people)
    await db.flush()
    orgs = [
        Organization(id=uuid4(), name="Demo", slug=uuid4().hex, created_by_user_id=people[0].id)
        for _ in range(2)
    ]
    db.add_all(orgs)
    await db.flush()
    members = [
        OrganizationMember(organization_id=org.id, user_id=person.id, role="member")
        for org in orgs
        for person in people
    ]
    db.add_all(members)
    await db.flush()
    await onboarding_repo.save(
        db, member=members[0], data=OnboardingUpdate(goal="meeting", completed=True)
    )
    for index, member in enumerate(members):
        stored = await member_repo.get(
            db, organization_id=member.organization_id, user_id=member.user_id
        )
        assert stored is not None
        assert stored.onboarding_goal == ("meeting" if index == 0 else None)
        assert (stored.onboarding_completed_at is not None) == (index == 0)
        assert stored.onboarding_dismissed_at is None


async def test_the_database_refuses_unknown_start_goals(db: AsyncSession) -> None:
    person = User(id=uuid4(), email=f"{uuid4().hex}@example.com", is_active=True)
    db.add(person)
    await db.flush()
    org = Organization(id=uuid4(), name="Demo", slug=uuid4().hex, created_by_user_id=person.id)
    db.add(org)
    await db.flush()
    member = OrganizationMember(organization_id=org.id, user_id=person.id, role="member")
    db.add(member)
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                OrganizationMember.__table__.update()
                .where(OrganizationMember.id == member.id)
                .values(onboarding_goal="unknown")
            )


async def test_current_step_is_durable_and_scoped_to_the_membership(db: AsyncSession) -> None:
    person = User(id=uuid4(), email=f"{uuid4().hex}@example.com", is_active=True)
    db.add(person)
    await db.flush()
    orgs = [
        Organization(id=uuid4(), name="Progress", slug=uuid4().hex, created_by_user_id=person.id)
        for _ in range(2)
    ]
    db.add_all(orgs)
    await db.flush()
    members = [
        OrganizationMember(organization_id=org.id, user_id=person.id, role="member") for org in orgs
    ]
    db.add_all(members)
    await db.flush()
    await onboarding_repo.save(
        db, member=members[0], data=OnboardingUpdate(current_step="member.models")
    )
    await db.refresh(members[0])
    await db.refresh(members[1])
    assert members[0].onboarding_current_step == "member.models"
    assert members[0].onboarding_updated_at is not None
    assert members[1].onboarding_current_step is None
    assert members[1].onboarding_updated_at is None
    from sqlalchemy import update

    with pytest.raises(IntegrityError, match="ck_org_member_onboarding_step"):
        await db.execute(
            update(OrganizationMember)
            .where(OrganizationMember.id == members[0].id)
            .values(onboarding_current_step="not-a-real-step")
        )
    await db.rollback()
