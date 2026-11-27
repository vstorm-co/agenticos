"""Query contracts complement real PostgreSQL completion and lock contenders."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import onboarding_repo

pytestmark = pytest.mark.anyio


async def test_first_deployment_write_upserts_then_locks_and_refreshes_the_singleton():
    row = DeploymentSettings()
    first, second = MagicMock(), MagicMock()
    second.scalar_one.return_value = row
    db = AsyncMock()
    db.execute.side_effect = [first, second]
    assert await onboarding_repo.deployment_for_update(db) is row
    insert, lock = [call.args[0] for call in db.execute.await_args_list]
    assert "ON CONFLICT DO NOTHING" in str(insert.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in str(lock.compile(dialect=postgresql.dialect()))
    assert lock.get_execution_options()["populate_existing"] is True
    db.commit.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("found", [False, True])
async def test_shared_progress_lock_is_tenant_scoped_and_refreshes_preloaded_rows(found):
    org_id = uuid4()
    row = Organization(id=org_id) if found else None
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = AsyncMock()
    db.execute.return_value = result
    assert await onboarding_repo.organization_for_update(db, org_id) is row
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert org_id in compiled.params.values() and "FOR UPDATE" in str(compiled)
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.security
@pytest.mark.parametrize("found", [False, True])
async def test_shared_write_rechecks_both_current_person_and_membership_under_share_lock(found):
    org_id, user_id = uuid4(), uuid4()
    pair = (
        (OrganizationMember(organization_id=org_id, user_id=user_id), User(id=user_id))
        if found
        else None
    )
    result = MagicMock()
    result.one_or_none.return_value = pair
    db = AsyncMock()
    db.execute.return_value = result
    assert (
        await onboarding_repo.shared_identity(db, organization_id=org_id, user_id=user_id) == pair
    )
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert {org_id, user_id} <= set(compiled.params.values())
    assert "FOR SHARE OF organization_members, users" in str(compiled)
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.security
@pytest.mark.parametrize("found", [False, True])
async def test_no_organization_actor_recheck_is_account_scoped_and_refreshes_admin_flag(found):
    user_id = uuid4()
    actor = User(id=user_id) if found else None
    result = MagicMock()
    result.scalar_one_or_none.return_value = actor
    db = AsyncMock()
    db.execute.return_value = result
    assert await onboarding_repo.deployment_actor(db, user_id) is actor
    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert user_id in compiled.params.values() and "FOR SHARE" in str(compiled)
    assert statement.get_execution_options()["populate_existing"] is True
