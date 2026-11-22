"""Organization member listings report recorded setup progress in batches."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import OrganizationMember
from app.db.models.user import User
from app.repositories import audit_log_repo, member_repo, user_repo
from app.services.member import MemberService

pytestmark = pytest.mark.anyio


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
