"""A request reads the caller's membership once.

`get_active_organization` reads the membership and the organization together and
keeps the membership on the request; `get_auth_context` builds the context from
it instead of reading the same row again (#2248). Here rather than in the unit
suite because the join is Postgres's answer, not a mock's.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from app.api.deps import get_active_organization, get_auth_context
from app.core.exceptions import NotFoundError
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import member as member_repo

pytestmark = pytest.mark.anyio


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, founder: User) -> Organization:
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _join(db, organization: Organization, user: User, role: str) -> None:
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=organization.id, user_id=user.id, role=role
        )
    )
    await db.flush()


async def test_the_auth_context_reuses_the_membership_the_organization_read(db) -> None:
    user = await _user(db)
    organization = await _org(db, user)
    await _join(db, organization, user, "admin")
    request = _request()

    org = await get_active_organization(request, user, db, x_organization_id=organization.id)
    with patch("app.api.deps._member_repo.get", new=AsyncMock()) as second_read:
        ctx = await get_auth_context(request, user, org, db)

    assert org.id == organization.id
    assert ctx.role == "admin"
    second_read.assert_not_awaited()


async def test_a_membership_of_another_organization_is_not_reused(db) -> None:
    user = await _user(db)
    first, second = await _org(db, user), await _org(db, user)
    await _join(db, first, user, "admin")
    await _join(db, second, user, "member")
    request = _request()

    await get_active_organization(request, user, db, x_organization_id=first.id)
    ctx = await get_auth_context(request, user, second, db)

    assert ctx.organization_id == second.id
    assert ctx.role == "member"


async def test_a_non_member_is_refused_like_a_missing_organization(db) -> None:
    founder, stranger = await _user(db), await _user(db)
    organization = await _org(db, founder)
    await _join(db, organization, founder, "owner")

    for organization_id in (organization.id, uuid.uuid4()):
        with pytest.raises(NotFoundError) as refused:
            await get_active_organization(
                _request(), stranger, db, x_organization_id=organization_id
            )
        assert refused.value.message == "Organization not found or access denied"


async def test_get_with_organization_returns_the_pair(db) -> None:
    user = await _user(db)
    organization = await _org(db, user)
    await _join(db, organization, user, "member")

    found = await member_repo.get_with_organization(
        db, organization_id=organization.id, user_id=user.id
    )

    assert found is not None
    membership, org = found
    assert (membership.user_id, membership.role) == (user.id, "member")
    assert org.id == organization.id
