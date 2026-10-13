"""Deleting a user who touched an invitation no longer 500s on a NO-ACTION FK.

Three foreign keys into `users.id` - who invited a member, who authored an
invitation, who accepted one - carried no `ondelete`, so PostgreSQL's NO ACTION
made any of them an absolute bar on deleting the referenced user (#1110). #9
reconciled the CHECK-versus-cascade collisions, but a user who had ever invited
another member still failed `DELETE /users/{id}` with a foreign-key violation.

Integration, not unit: the whole point is what the database does to the
neighbouring invite rows when the referenced user is deleted, which a mock
cannot show.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.organization import (
    Invitation,
    InvitationStatus,
    Organization,
    OrganizationMember,
)
from app.db.models.user import User
from app.services.user import UserService

pytestmark = pytest.mark.anyio


def _user(*, is_app_admin: bool = False) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
        is_app_admin=is_app_admin,
    )


async def _org(db: AsyncSession, creator: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        is_personal=False,
        created_by_user_id=creator.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=creator.id, role="owner"
        )
    )
    await db.flush()
    return org


async def _member(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, *, invited_by: uuid.UUID | None
) -> OrganizationMember:
    member = OrganizationMember(
        id=uuid.uuid4(),
        organization_id=org_id,
        user_id=user_id,
        role="member",
        invited_by_user_id=invited_by,
    )
    db.add(member)
    await db.flush()
    return member


def _invitation(org_id: uuid.UUID, inviter_id: uuid.UUID) -> Invitation:
    return Invitation(
        id=uuid.uuid4(),
        organization_id=org_id,
        email=f"{uuid.uuid4().hex}@example.com",
        role="member",
        invited_by_user_id=inviter_id,
        token=uuid.uuid4().hex,
        status=InvitationStatus.PENDING.value,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


async def test_deleting_a_user_who_invited_another_nulls_the_invite_refs(db: AsyncSession) -> None:
    owner = _user()
    inviter = _user()
    invitee = _user()
    db.add_all([owner, inviter, invitee])
    await db.flush()
    org = await _org(db, owner)
    await _member(db, org.id, inviter.id, invited_by=None)
    invitee_member = await _member(db, org.id, invitee.id, invited_by=inviter.id)
    invitation = _invitation(org.id, inviter.id)
    db.add(invitation)
    await db.flush()
    inviter_id = inviter.id

    await UserService(db).delete(inviter_id)
    await db.flush()

    assert await db.get(User, inviter_id) is None
    await db.refresh(invitee_member)
    assert invitee_member.invited_by_user_id is None
    await db.refresh(invitation)
    assert invitation.invited_by_user_id is None


async def test_deleting_the_accepter_of_an_invitation_nulls_that_reference(
    db: AsyncSession,
) -> None:
    owner = _user()
    accepter = _user()
    db.add_all([owner, accepter])
    await db.flush()
    org = await _org(db, owner)
    invitation = _invitation(org.id, owner.id)
    invitation.status = InvitationStatus.ACCEPTED.value
    invitation.accepted_by_user_id = accepter.id
    invitation.accepted_at = datetime.now(UTC)
    db.add(invitation)
    await db.flush()
    accepter_id = accepter.id

    await UserService(db).delete(accepter_id)
    await db.flush()

    assert await db.get(User, accepter_id) is None
    await db.refresh(invitation)
    assert invitation.accepted_by_user_id is None


async def test_the_bulk_delete_nulls_the_invite_ref_it_no_longer_blocks_on(
    db: AsyncSession,
) -> None:
    """The SET NULL fires on the bulk path too, not only single-row `delete()`.

    `delete_non_admins` is a bare `DELETE FROM users` and does not go through
    `_release_owned_rows`, so it exercises the FK's own `ondelete` rather than a
    service reconciliation. The author here owns no personal org, which isolates
    the invite FK: `organizations.created_by_user_id` is still `RESTRICT`, so a
    real `seed --clear` of users that each own a personal org is a separate bar
    this change does not lift (filed follow-up).
    """
    admin = _user(is_app_admin=True)
    inviter = _user()
    db.add_all([admin, inviter])
    await db.flush()
    org = await _org(db, admin)
    await _member(db, org.id, inviter.id, invited_by=None)
    invitation = _invitation(org.id, inviter.id)
    db.add(invitation)
    await db.flush()
    inviter_id, admin_id = inviter.id, admin.id

    removed = await UserService(db).delete_non_admins()
    await db.flush()

    assert removed >= 1
    assert await db.get(User, inviter_id) is None
    assert await db.get(User, admin_id) is not None
    await db.refresh(invitation)
    assert invitation.invited_by_user_id is None
