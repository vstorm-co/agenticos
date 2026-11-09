"""The invitation sweep against a real database.

A mock can pin who calls the sweep; only Postgres can say which rows the
UPDATE actually touches. What matters is the boundary: a pending invitation
past its expiry flips to `expired`, and nothing else moves - not the one
still within its window, and not the one an administrator already revoked,
whose status records a decision the sweep must not write over (#456).
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.organization import (
    Invitation,
    InvitationStatus,
    Organization,
    OrganizationMember,
)
from app.db.models.user import User
from app.repositories import invitation_repo

pytestmark = pytest.mark.anyio


async def _invitation(db, *, status: str, expires_at: datetime) -> Invitation:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    invite = Invitation(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=f"{uuid.uuid4().hex}@example.com",
        invited_by_user_id=user.id,
        token=secrets.token_urlsafe(32),
        status=status,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()
    return invite


async def test_the_sweep_expires_exactly_the_stale_pending_rows(db):
    hour_ago = datetime.now(UTC) - timedelta(hours=1)
    next_week = datetime.now(UTC) + timedelta(days=7)
    stale = await _invitation(db, status=InvitationStatus.PENDING.value, expires_at=hour_ago)
    fresh = await _invitation(db, status=InvitationStatus.PENDING.value, expires_at=next_week)
    revoked = await _invitation(db, status=InvitationStatus.REVOKED.value, expires_at=hour_ago)

    assert await invitation_repo.expire_stale(db) == 1

    for invite in (stale, fresh, revoked):
        await db.refresh(invite)
    assert stale.status == InvitationStatus.EXPIRED.value
    assert fresh.status == InvitationStatus.PENDING.value
    assert revoked.status == InvitationStatus.REVOKED.value


async def test_received_inbox_excludes_other_people_links_stale_invites_and_memberships(db):
    person = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", is_active=True)
    db.add(person)
    await db.flush()
    expected = None
    now = datetime.now(UTC)
    for case in ["live", "expired", "revoked", "accepted", "other", "link", "member"]:
        invite = await _invitation(
            db,
            status=case if case in ("revoked", "accepted") else "pending",
            expires_at=now + timedelta(days=-1 if case == "expired" else 1),
        )
        invite.email = (
            None if case == "link" else "other@example.com" if case == "other" else person.email
        )
        if case == "member":
            db.add(
                OrganizationMember(
                    user_id=person.id, organization_id=invite.organization_id, role="member"
                )
            )
        if case == "live":
            expected = invite.id
    await db.flush()
    rows = await invitation_repo.received(db, email=person.email.upper(), user_id=person.id)
    assert [invite.id for invite, _ in rows] == [expected]
