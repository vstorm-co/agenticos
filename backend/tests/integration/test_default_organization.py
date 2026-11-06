"""Where a new account starts, against a real database (#2156).

Here rather than in the unit suite for two reasons a mock cannot answer: the
membership row a sign-up writes is what every later request resolves its tenant
from, and clearing the setting when its organization is deleted is the foreign
key's `ON DELETE SET NULL`, not anything this code does.
"""

import uuid

import pytest
from sqlalchemy import delete, text

from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import deployment_settings_repo, member_repo, organization_repo
from app.services.organization import OrganizationService

pytestmark = pytest.mark.anyio


async def _person(db, email: str) -> User:
    user = User(id=uuid.uuid4(), email=email, hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _company(db, creator: User) -> Organization:
    return await organization_repo.create(
        db, name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=creator.id
    )


async def test_a_company_deployment_starts_a_newcomer_in_the_company(db) -> None:
    founder = await _person(db, "founder@acme.com")
    company = await _company(db, founder)
    await deployment_settings_repo.upsert(
        db,
        update_data={
            "personal_organizations": False,
            "default_organization_id": company.id,
            "default_organization_role": "builder",
        },
    )
    newcomer = await _person(db, "ada@acme.com")

    service = OrganizationService(db)
    await service.settle_new_account(newcomer.id, newcomer.email)

    membership = await member_repo.get(db, organization_id=company.id, user_id=newcomer.id)
    assert membership is not None and membership.role == "builder"
    assert await organization_repo.get_personal_for_user(db, newcomer.id) is None
    landing = await service.fallback_for(newcomer.id)
    assert landing is not None and landing.id == company.id


async def test_deleting_the_default_organization_clears_the_setting(db) -> None:
    founder = await _person(db, "founder@acme.com")
    company = await _company(db, founder)
    await deployment_settings_repo.upsert(db, update_data={"default_organization_id": company.id})

    await db.execute(delete(Organization).where(Organization.id == company.id))
    await db.flush()
    row = await deployment_settings_repo.get(db)
    assert row is not None
    await db.refresh(row)

    assert row.default_organization_id is None


@pytest.mark.security
async def test_new_organizations_allow_chat_approval_waivers_from_orm_and_database(db) -> None:
    founder = await _person(db, "founder@acme.com")
    company = await _company(db, founder)
    assert company.chat_may_waive_approvals is True
    value = await db.scalar(
        text(
            "INSERT INTO organizations (id, name, slug, created_by_user_id, is_personal) "
            "VALUES (:id, 'Raw organization', :slug, :creator, false) "
            "RETURNING chat_may_waive_approvals"
        ),
        {"id": uuid.uuid4(), "slug": f"raw-{uuid.uuid4().hex}", "creator": founder.id},
    )
    assert value is True


@pytest.mark.security
async def test_explicit_organization_approval_waiver_opt_out_is_preserved(db) -> None:
    founder = await _person(db, "founder@acme.com")
    company = Organization(
        id=uuid.uuid4(),
        name="Opted out",
        slug=f"opt-out-{uuid.uuid4().hex}",
        created_by_user_id=founder.id,
        chat_may_waive_approvals=False,
    )
    db.add(company)
    await db.flush()
    await db.refresh(company)
    assert company.chat_may_waive_approvals is False
