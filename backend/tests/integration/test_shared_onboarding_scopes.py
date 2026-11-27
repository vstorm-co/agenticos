"""Real shared completion, tenant isolation and migration compatibility."""

import asyncio
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import onboarding_repo
from app.schemas.onboarding import OnboardingScopeUpdate
from app.services.onboarding import OnboardingService

pytestmark = pytest.mark.anyio


async def seed(db: AsyncSession) -> tuple[list[User], list[Organization], list[OrganizationMember]]:
    people = [User(id=uuid4(), email=f"{uuid4()}@example.com", is_active=True) for _ in range(2)]
    db.add_all(people)
    await db.flush()
    orgs = [
        Organization(id=uuid4(), name="Team", slug=uuid4().hex, created_by_user_id=people[0].id)
        for _ in range(2)
    ]
    db.add_all(orgs)
    await db.flush()
    members = [
        OrganizationMember(user_id=person.id, organization_id=org.id, role="admin")
        for org in orgs
        for person in people
    ]
    db.add_all(members)
    await db.flush()
    return people, orgs, members


@pytest.mark.parametrize("scope", ["deployment", "organization"])
async def test_concurrent_administrators_cannot_reopen_or_replace_shared_completion(
    db, engine, scope
):
    _, orgs, _ = await seed(db)
    org_id = orgs[0].id
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    first_locked, contender_started = asyncio.Event(), asyncio.Event()

    async def first() -> datetime | None:
        async with factory() as session:
            row = (
                await onboarding_repo.deployment_for_update(session)
                if scope == "deployment"
                else await onboarding_repo.organization_for_update(session, org_id)
            )
            assert row is not None
            first_locked.set()
            await contender_started.wait()
            await onboarding_repo.save_shared(
                session, row=row, data=OnboardingScopeUpdate(completed=True)
            )
            stamp = row.onboarding_completed_at
            await session.commit()
            return stamp

    async def second() -> datetime | None:
        await first_locked.wait()
        async with factory() as session:
            # Deliberately preload the old state before waiting on the lock.
            preloaded = await session.get(Organization, org_id) if scope == "organization" else None
            contender_started.set()
            row = (
                await onboarding_repo.deployment_for_update(session)
                if scope == "deployment"
                else await onboarding_repo.organization_for_update(session, org_id)
            )
            assert row is not None
            if preloaded is not None:
                assert row is preloaded
            await onboarding_repo.save_shared(
                session,
                row=row,
                data=OnboardingScopeUpdate(
                    current_step="admin.deployment" if scope == "deployment" else "admin.models"
                ),
            )
            assert row.onboarding_current_step is None
            await session.commit()
            return row.onboarding_completed_at

    stamps = await asyncio.wait_for(asyncio.gather(first(), second()), timeout=10)
    assert stamps[0] is not None and stamps[0] == stamps[1]


@pytest.mark.security
async def test_organization_completion_is_shared_with_other_admins_not_other_tenants_or_people(db):
    people, orgs, members = await seed(db)
    row = await onboarding_repo.organization_for_update(db, orgs[0].id)
    await onboarding_repo.save_shared(db, row=row, data=OnboardingScopeUpdate(completed=True))
    await db.refresh(orgs[1])
    assert orgs[1].onboarding_completed_at is None
    for member in members:
        await db.refresh(member)
        assert member.onboarding_completed_at is None
    reader = OnboardingService(db)
    for person in people:
        ctx = AuthContext(user_id=person.id, organization_id=orgs[0].id, role="admin")
        member = next(
            item
            for item in members
            if item.user_id == person.id and item.organization_id == orgs[0].id
        )
        scopes = reader._scopes(ctx, member, person, orgs[0], None, None)
        assert scopes[1].completed and scopes[-1].completed is False


@pytest.mark.security
async def test_stale_administrator_context_cannot_complete_after_membership_demotion(db):
    people, orgs, members = await seed(db)
    ctx = AuthContext(user_id=people[0].id, organization_id=orgs[0].id, role="admin")
    members[0].role = "member"
    await db.flush()
    with pytest.raises(AuthorizationError):
        await OnboardingService(db).update_scope(
            ctx, "organization", OnboardingScopeUpdate(completed=True)
        )
    assert orgs[0].onboarding_completed_at is None


@pytest.mark.security
async def test_organization_selection_cannot_borrow_membership_from_another_tenant(db):
    people, orgs, members = await seed(db)
    for member in members:
        if member.organization_id == orgs[1].id:
            await db.delete(member)
    await db.flush()
    with pytest.raises(NotFoundError):
        await OnboardingService(db).update_scope(
            AuthContext(user_id=people[0].id, organization_id=orgs[1].id, role="owner"),
            "organization",
            OnboardingScopeUpdate(completed=True),
        )
    assert orgs[1].onboarding_completed_at is None


@pytest.mark.parametrize("scope", ["deployment", "organization"])
async def test_scope_step_constraints_are_enforced_by_postgres(db, scope):
    _, orgs, _ = await seed(db)
    row = await onboarding_repo.deployment_for_update(db) if scope == "deployment" else orgs[0]
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                row.__table__.update()
                .where(row.__table__.c.id == row.id)
                .values(onboarding_current_step="member.tools")
            )


async def test_upgrade_leaves_existing_shared_stages_unfinished_and_preserves_personal_completion(
    db,
):
    _, orgs, members = await seed(db)
    stamp = datetime.now(UTC)
    members[0].onboarding_completed_at = stamp
    members[0].onboarding_dismissed_at = stamp
    await onboarding_repo.deployment_for_update(db)
    await db.flush()
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0385_shared_onboarding_scopes.py"
    spec = importlib.util.spec_from_file_location("shared_onboarding_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0384_environment_layout_driver"

    def cycle(session: Session) -> None:
        connection = session.connection()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
        assert (
            connection.execute(
                text("SELECT onboarding_completed_at FROM deployment_settings")
            ).scalar_one()
            is None
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM organizations WHERE onboarding_completed_at IS NOT NULL")
            ).scalar_one()
            == 0
        )
        stored = connection.execute(
            text(
                "SELECT onboarding_completed_at,onboarding_dismissed_at FROM organization_members WHERE id=:id"
            ),
            {"id": members[0].id},
        ).one()
        assert tuple(stored) == (stamp, stamp)

    await db.run_sync(cycle)


@pytest.mark.security
async def test_missing_shared_identity_and_deployment_actor_are_never_invented(db):
    assert (
        await onboarding_repo.shared_identity(db, organization_id=uuid4(), user_id=uuid4()) is None
    )
    assert await onboarding_repo.deployment_actor(db, uuid4()) is None
    assert await onboarding_repo.organization_for_update(db, uuid4()) is None


async def test_real_service_completion_reaches_coadmin_and_no_organization_start(db, monkeypatch):
    from unittest.mock import AsyncMock

    people, orgs, _ = await seed(db)
    monkeypatch.setattr(OnboardingService, "_agents", AsyncMock(return_value=[]))
    monkeypatch.setattr(OnboardingService, "_setup_agent", AsyncMock(return_value=None))
    service = OnboardingService(db)
    ctx = AuthContext(user_id=people[0].id, organization_id=orgs[0].id, role="admin")
    result = await service.update_scope(ctx, "organization", OnboardingScopeUpdate(completed=True))
    assert result.scopes[1].completed
    other = await service.state(
        AuthContext(user_id=people[1].id, organization_id=orgs[0].id, role="admin")
    )
    assert other.scopes[1].completed_at == result.scopes[1].completed_at
    people[0].is_app_admin = people[1].is_app_admin = True
    await db.flush()
    deployed = await service.update_deployment(people[0], OnboardingScopeUpdate(completed=True))
    coadmin = await service.deployment_state(people[1])
    assert (
        deployed.organization_id is None
        and coadmin.scopes[0].completed_at == deployed.scopes[0].completed_at
    )
    assert not other.completed and not coadmin.completed
