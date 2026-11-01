"""A connected mailbox is read on its own interval, decided per grant in SQL."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import mcp_connection_repo
from app.services.mcp_connection import McpConnectionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


async def _organization(db: AsyncSession) -> tuple[Organization, User]:
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid4()}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    return org, user


async def _grant(
    db: AsyncSession,
    org: Organization,
    user: User,
    *,
    portal_key: str = "google",
    interval: int = 1,
    polled_ago: timedelta | None = None,
) -> McpConnection:
    row = McpConnection(
        id=uuid4(),
        scope="org",
        organization_id=org.id,
        created_by_user_id=user.id,
        name=f"portal-{portal_key}",
        url="https://srv/mcp",
        auth_type="oauth",
        oauth_payload="sealed",
        is_enabled=True,
        purpose="portal",
        portal_key=portal_key,
        poll_interval_minutes=interval,
        polled_at=None if polled_ago is None else NOW - polled_ago,
    )
    db.add(row)
    await db.flush()
    return row


async def test_a_grant_is_due_once_its_own_interval_has_passed(db: AsyncSession) -> None:
    org, user = await _organization(db)
    other, other_user = await _organization(db)
    fresh = await _grant(db, org, user, interval=15, polled_ago=timedelta(minutes=5))
    due = await _grant(db, other, other_user, interval=15, polled_ago=timedelta(minutes=16))
    never = await _grant(db, org, user, portal_key="microsoft", interval=60)
    hourly = await _grant(
        db, other, other_user, portal_key="microsoft", interval=60, polled_ago=timedelta(minutes=59)
    )
    minutely = await _grant(
        db, org, user, portal_key="google_drive", polled_ago=timedelta(seconds=56)
    )
    too_soon = await _grant(
        db, other, other_user, portal_key="google_drive", polled_ago=timedelta(seconds=30)
    )
    keys = ["google", "microsoft", "google_drive"]

    candidates = await mcp_connection_repo.portal_poll_candidates(
        db, portal_keys=keys, now=NOW, limit=50
    )

    assert set(candidates) == {due.id, never.id, minutely.id}
    for grant, expected in [
        (fresh, False),
        (due, True),
        (never, True),
        (hourly, False),
        (minutely, True),
        (too_soon, False),
    ]:
        claimed = await mcp_connection_repo.claim_portal_grant_to_poll(
            db, connection_id=grant.id, portal_keys=keys, now=NOW
        )
        assert (claimed is not None) is expected


async def test_the_interval_is_limited_to_the_allowed_set(db: AsyncSession) -> None:
    org, user = await _organization(db)
    assert (await _grant(db, org, user)).poll_interval_minutes == 1
    with pytest.raises(IntegrityError, match="ck_mcp_connection_poll_interval"):
        await _grant(db, org, user, portal_key="microsoft", interval=7)


async def test_setting_it_is_audited_and_scoped_to_the_organization(db: AsyncSession) -> None:
    org, user = await _organization(db)
    other, other_user = await _organization(db)
    mine = await _grant(db, org, user)
    theirs = await _grant(db, other, other_user)
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)
    service = McpConnectionService(db)

    updated = await service.set_poll_interval(ctx, connection_id=mine.id, minutes=30)
    await service.set_poll_interval(ctx, connection_id=mine.id, minutes=30)

    assert updated.poll_interval_minutes == 30
    entries = (
        (
            await db.execute(
                select(AppAdminAuditLog).where(AppAdminAuditLog.organization_id == org.id)
            )
        )
        .scalars()
        .all()
    )
    assert [(e.action, e.details) for e in entries] == [
        (
            "mcp_connection.poll_interval_set",
            {"portal_key": "google", "from_minutes": 1, "to_minutes": 30},
        )
    ]
    with pytest.raises(NotFoundError):
        await service.set_poll_interval(ctx, connection_id=theirs.id, minutes=5)
    await db.refresh(theirs)
    assert theirs.poll_interval_minutes == 1


async def test_a_grant_that_is_not_a_mailbox_has_no_interval(db: AsyncSession) -> None:
    org, user = await _organization(db)
    webhook = await _grant(db, org, user, portal_key="github_app")
    unknown = await _grant(db, org, user, portal_key="retired")
    calendar = await _grant(db, org, user, portal_key="google_calendar")
    files = await _grant(db, org, user, portal_key="google_drive")
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)

    for grant in (webhook, unknown, calendar, files):
        with pytest.raises(NotFoundError):
            await McpConnectionService(db).set_poll_interval(ctx, connection_id=grant.id, minutes=5)
