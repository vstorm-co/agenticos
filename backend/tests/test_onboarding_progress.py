"""Administrative listings report recorded, tenant-scoped setup progress in batches."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import OrganizationMember
from app.db.models.user import User
from app.repositories import audit_log_repo, member_repo, onboarding_repo, session_repo, user_repo
from app.services.member import MemberService
from app.services.user import UserService

pytestmark = pytest.mark.anyio


async def test_admin_lists_all_membership_progress_and_empty_accounts_in_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    person = User(
        id=uuid4(),
        email="member@example.com",
        created_at=now,
        is_active=True,
        is_app_admin=False,
        onboarding_completed_at=now,
    )
    empty = User(
        id=uuid4(), email="empty@example.com", created_at=now, is_active=True, is_app_admin=False
    )
    old = OrganizationMember(
        id=uuid4(),
        user_id=person.id,
        organization_id=uuid4(),
        role="member",
        joined_at=now - timedelta(days=1),
    )
    new = OrganizationMember(
        id=uuid4(),
        user_id=person.id,
        organization_id=uuid4(),
        role="member",
        joined_at=now + timedelta(days=1),
        onboarding_current_step="member.tools",
        onboarding_updated_at=now,
    )
    rows = [
        onboarding_repo.MemberOnboardingRow(old, "Old workspace", now),
        onboarding_repo.MemberOnboardingRow(new, "New workspace", now),
    ]
    monkeypatch.setattr(
        user_repo, "admin_list_with_counts", AsyncMock(return_value=([(person, 0), (empty, 0)], 2))
    )
    monkeypatch.setattr(session_repo, "admin_activity_for", AsyncMock(return_value={}))
    progress = AsyncMock(return_value=rows)
    monkeypatch.setattr(onboarding_repo, "progress_for_users", progress)
    db = AsyncMock(spec=AsyncSession)
    result = await UserService(db).admin_list_with_counts()
    progress.assert_awaited_once_with(db, [person.id, empty.id])
    assert result.items[0].onboarding_completed_at == now
    assert result.items[0].onboarding[0].completed_at == now
    assert result.items[0].onboarding[0].current_step is None
    assert result.items[0].onboarding[1].completed_at is None
    assert result.items[0].onboarding[1].current_step == "member.tools"
    assert result.items[1].onboarding == []
    assert result.items[1].onboarding_completed_at is None


async def test_org_member_progress_uses_only_the_listed_org_and_batch_account_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    org_id, user_id = uuid4(), uuid4()
    member = OrganizationMember(
        id=uuid4(),
        user_id=user_id,
        organization_id=org_id,
        role="owner",
        joined_at=now - timedelta(days=1),
    )
    person = User(id=user_id, email="member@example.com", onboarding_completed_at=now)
    monkeypatch.setattr(member_repo, "get", AsyncMock(return_value=member))
    listing = AsyncMock(return_value=[(member, person.email, None, None, None)])
    monkeypatch.setattr(member_repo, "list_for_org", listing)
    monkeypatch.setattr(member_repo, "count_for_org", AsyncMock(return_value=1))
    monkeypatch.setattr(audit_log_repo, "latest_member_actions", AsyncMock(return_value={}))
    people = AsyncMock(return_value=[person])
    monkeypatch.setattr(user_repo, "get_by_ids", people)
    db = AsyncMock(spec=AsyncSession)
    result, total = await MemberService(db).list_for_org(org_id, user_id)
    listing.assert_awaited_once_with(db, org_id, skip=0, limit=100)
    people.assert_awaited_once_with(db, [user_id])
    assert total == 1 and result[0][5] == now


async def test_admin_progress_query_is_bounded_to_the_current_user_page() -> None:
    db = AsyncMock(spec=AsyncSession)
    result = await onboarding_repo.progress_for_users(db, [])
    assert result == []
    db.execute.assert_not_awaited()
    from unittest.mock import MagicMock

    selected = MagicMock()
    user_id = uuid4()
    member = OrganizationMember(user_id=user_id, organization_id=uuid4(), role="member")
    selected.all.return_value = [(member, "Workspace", None)]
    db.execute.return_value = selected
    assert await onboarding_repo.progress_for_users(db, [user_id]) == [
        onboarding_repo.MemberOnboardingRow(member, "Workspace", None)
    ]
    query = db.execute.await_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "organization_members.user_id IN" in sql
    assert str(user_id) in sql
    assert "JOIN organizations" in sql and "JOIN users" in sql
