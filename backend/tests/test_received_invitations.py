"""A recipient discovers and accepts their own addressed invitation, without its token."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.services import invitation as module
from app.services.invitation import InvitationService
from app.services.session import SessionService

pytestmark = pytest.mark.anyio


@pytest.fixture
def received(monkeypatch):
    person = SimpleNamespace(id=uuid4(), email="Invitee@example.com")
    invite = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        email="invitee@example.com",
        token="private-token",
        role="member",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    monkeypatch.setattr(module.user_repo, "get_by_id", AsyncMock(return_value=person))
    monkeypatch.setattr(module.invitation_repo, "get_by_id", AsyncMock(return_value=invite))
    monkeypatch.setattr(
        module.invitation_repo,
        "received",
        AsyncMock(
            return_value=[
                (
                    invite,
                    SimpleNamespace(
                        id=invite.organization_id,
                        name="Acme",
                        avatar_url="avatars/acme.png",
                        avatar_color=3,
                    ),
                )
            ]
        ),
    )
    monkeypatch.setattr(SessionService, "has_mailbox_proof", AsyncMock(return_value=True))
    service = InvitationService(MagicMock())
    service.accept = AsyncMock(return_value=invite)
    return person, invite, service


async def test_received_list_uses_current_account_email_and_never_exposes_token(received):
    person, invite, service = received
    rows = await service.received(person.id)
    module.invitation_repo.received.assert_awaited_once_with(
        service.db, email=person.email, user_id=person.id, skip=0, limit=50, invitation_id=None
    )
    assert rows[0].organization_has_avatar is True
    assert rows[0].organization_avatar_color == 3
    assert "avatars/acme.png" not in rows[0].model_dump_json()
    assert rows[0].organization_name == "Acme"
    assert rows[0].id == invite.id
    assert "token" not in rows[0].model_dump_json()


async def test_received_accept_keeps_existing_locked_acceptance_and_role_checks(received):
    person, invite, service = received
    assert await service.accept_received(invite.id, person.id) is invite
    service.accept.assert_awaited_once_with(invite.token, accepting_user_id=person.id)


@pytest.mark.parametrize(
    "case", ["other_email", "shareable", "missing", "missing_user", "changed_email"]
)
async def test_received_invitation_cannot_be_claimed_by_another_address(received, case):
    person, invite, service = received
    if case in ("other_email", "changed_email"):
        person.email = "someone-else@example.com"
    if case == "shareable":
        invite.email = None
    if case == "missing":
        module.invitation_repo.get_by_id.return_value = None
    if case == "missing_user":
        module.user_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.accept_received(invite.id, person.id)
    service.accept.assert_not_awaited()


async def test_expired_or_revoked_acceptance_failure_is_not_reported_as_joined(received):
    person, invite, service = received
    service.accept.side_effect = BadRequestError(message="Invitation is no longer valid")
    with pytest.raises(BadRequestError):
        await service.accept_received(invite.id, person.id)


async def test_missing_account_cannot_list_invitations(received):
    person, _, service = received
    module.user_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.received(person.id)


async def test_received_repository_normalizes_address_and_keeps_account_scope():
    from app.repositories import invitation_repo

    user_id = uuid4()
    invite, organization = MagicMock(), MagicMock()
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.execute.return_value.all.return_value = [(invite, organization)]
    assert await invitation_repo.received(db, email=" Invitee@EXAMPLE.com ", user_id=user_id) == [
        (invite, organization)
    ]
    compiled = db.execute.await_args.args[0].compile()
    assert "invitee@example.com" in compiled.params.values()
    assert user_id in compiled.params.values()
    assert "organization_members" in str(compiled)
    assert "invitations.expires_at >" in str(compiled)
    assert "invitations.status =" in str(compiled)
    assert "pending" in compiled.params.values()


async def test_recipient_can_preview_logo_without_membership(received):
    person, invite, service = received
    assert await service.received_avatar(invite.id, person.id) == "avatars/acme.png"
    module.invitation_repo.received.assert_awaited_once_with(
        service.db, email=person.email, user_id=person.id, skip=0, limit=1, invitation_id=invite.id
    )


@pytest.mark.parametrize(
    "case", ["unavailable_invitation", "other_invitation", "no_logo", "missing_user"]
)
async def test_logo_preview_requires_a_live_addressed_invitation(received, case):
    person, invite, service = received
    if case == "unavailable_invitation":
        module.invitation_repo.received.return_value = []
    elif case == "other_invitation":
        invite.id = uuid4()
    elif case == "no_logo":
        module.invitation_repo.received.return_value[0][1].avatar_url = None
    elif case == "missing_user":
        module.user_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.received_avatar(
            uuid4() if case == "other_invitation" else invite.id, person.id
        )


async def test_unproved_password_session_cannot_discover_accept_or_preview(received):
    person, invite, service = received
    SessionService.has_mailbox_proof.return_value = False
    assert await service.received(person.id) == []
    module.invitation_repo.received.assert_not_awaited()
    with pytest.raises(NotFoundError):
        await service.accept_received(invite.id, person.id)
    with pytest.raises(NotFoundError):
        await service.received_avatar(invite.id, person.id)
    service.accept.assert_not_awaited()


async def test_inbox_pagination_passes_offset_without_truncating_older_invitations(received):
    person, _, service = received
    await service.received(person.id, skip=150, limit=50)
    module.invitation_repo.received.assert_awaited_once_with(
        service.db, email=person.email, user_id=person.id, skip=150, limit=50, invitation_id=None
    )
