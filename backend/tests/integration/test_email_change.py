"""An address does not become an account's until somebody proves they read it.

`PATCH /users/me` accepted a new email address and started using it at once.
Every mail this deployment sends goes to that column - an invitation, a magic
link, a password reset, an approval request, a budget alert, and every
notification queued for the email channel - so an account whose address had been
changed to somewhere its owner cannot read is an account whose next reset link
goes to somebody else (#1772).

Against a real database, because three of the properties are the database's: the
staged column, the unique constraint that decides who gets a contested address,
and the row lock that stops one staging being confirmed twice.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import AlreadyExistsError, AuthenticationError, RateLimitError
from app.core.security import create_email_change_token
from app.db.models.user import User
from app.schemas.user import UserUpdate
from app.services import rate_limit
from app.services import user as user_module
from app.services.user import UserService

pytestmark = pytest.mark.anyio


async def _user(db, **overrides) -> User:
    fields = {
        "id": uuid.uuid4(),
        "email": f"{uuid.uuid4().hex}@example.com",
        "hashed_password": "x",
        "is_active": True,
        "is_app_admin": False,
    }
    fields.update(overrides)
    user = User(**fields)
    db.add(user)
    await db.flush()
    return user


class TestRequestingAChange:
    async def test_the_address_does_not_move_until_it_is_confirmed(self, db):
        user = await _user(db)
        original = user.email
        service = UserService(db)

        updated, token = await service.update_current(user, UserUpdate(email="new@example.com"))

        assert updated.email == original
        assert updated.pending_email == "new@example.com"
        assert token is not None

    async def test_the_rest_of_the_patch_still_applies(self, db):
        """Staging the address is not a refusal of the request it arrived in."""
        user = await _user(db)
        service = UserService(db)

        updated, _ = await service.update_current(
            user, UserUpdate(email="new@example.com", full_name="Renamed")
        )

        assert updated.full_name == "Renamed"
        assert updated.pending_email == "new@example.com"

    async def test_a_patch_with_no_address_stages_nothing_and_mails_nothing(self, db):
        user = await _user(db)
        service = UserService(db)

        updated, token = await service.update_current(user, UserUpdate(full_name="Renamed"))

        assert token is None
        assert updated.pending_email is None

    async def test_asking_for_the_address_it_already_has_clears_the_staging(self, db):
        """A form submitted twice is not an error a person can act on, and it
        must not leave an abandoned staging behind that a stale token could
        still confirm."""
        user = await _user(db)
        service = UserService(db)
        await service.update_current(user, UserUpdate(email="new@example.com"))

        updated, token = await service.update_current(user, UserUpdate(email=user.email))

        assert token is None
        assert updated.pending_email is None

    async def test_an_address_another_account_holds_is_refused(self, db):
        other = await _user(db)
        user = await _user(db)
        service = UserService(db)

        with pytest.raises(AlreadyExistsError):
            await service.update_current(user, UserUpdate(email=other.email))

        await db.refresh(user)
        assert user.pending_email is None

    async def test_two_accounts_may_stage_the_same_address(self, db):
        """Only the first to confirm gets it, and that is decided by the unique
        constraint on `email` at the moment it is decided. Refusing the second
        *request* would leak that somebody else is mid-change to an address."""
        first = await _user(db)
        second = await _user(db)
        service = UserService(db)

        await service.update_current(first, UserUpdate(email="contested@example.com"))
        await service.update_current(second, UserUpdate(email="contested@example.com"))

        assert first.pending_email == "contested@example.com"
        assert second.pending_email == "contested@example.com"


class TestConfirming:
    async def test_the_link_moves_the_address_and_clears_the_staging(self, db):
        user = await _user(db)
        service = UserService(db)
        _, token = await service.update_current(user, UserUpdate(email="new@example.com"))
        assert token is not None

        confirmed = await service.confirm_email_change(token)

        assert confirmed.email == "new@example.com"
        assert confirmed.pending_email is None

    async def test_the_same_link_twice_is_refused(self, db):
        """Single-use without a second table: the move clears the staging, so a
        replay finds nothing to move."""
        user = await _user(db)
        service = UserService(db)
        _, token = await service.update_current(user, UserUpdate(email="new@example.com"))
        assert token is not None
        await service.confirm_email_change(token)

        with pytest.raises(AuthenticationError):
            await service.confirm_email_change(token)

    async def test_a_token_for_an_address_no_longer_staged_is_refused(self, db):
        """A change asked for and then changed again: the first link must not
        confirm an address nobody is waiting on any more."""
        user = await _user(db)
        service = UserService(db)
        _, first = await service.update_current(user, UserUpdate(email="first@example.com"))
        await service.update_current(user, UserUpdate(email="second@example.com"))
        assert first is not None

        with pytest.raises(AuthenticationError):
            await service.confirm_email_change(first)

        await db.refresh(user)
        assert user.email not in {"first@example.com", "second@example.com"}

    async def test_a_token_of_the_wrong_kind_is_refused(self, db):
        """The `type` claim is what stops a magic link or a reset token being
        spent here."""
        from app.core.security import create_magic_link_token

        user = await _user(db)
        service = UserService(db)
        await service.update_current(user, UserUpdate(email="new@example.com"))

        with pytest.raises(AuthenticationError):
            await service.confirm_email_change(create_magic_link_token(subject=str(user.id)))

    async def test_a_token_for_an_account_that_is_gone_is_refused(self, db):
        user = await _user(db)
        token = create_email_change_token(
            subject=str(uuid.uuid4()), new_email=user.email, credential_version=1
        )

        with pytest.raises(AuthenticationError):
            await UserService(db).confirm_email_change(token)

    async def test_a_malformed_subject_is_refused(self, db):
        token = create_email_change_token(
            subject="not-a-uuid", new_email="new@example.com", credential_version=1
        )

        with pytest.raises(AuthenticationError):
            await UserService(db).confirm_email_change(token)

    async def test_an_address_taken_in_the_meantime_is_refused(self, db):
        """The request-time check is best-effort by construction; this is where
        a contested address is actually decided."""
        user = await _user(db)
        service = UserService(db)
        _, token = await service.update_current(user, UserUpdate(email="contested@example.com"))
        assert token is not None
        await _user(db, email="contested@example.com")

        with pytest.raises(AlreadyExistsError):
            await service.confirm_email_change(token)

        await db.refresh(user)
        assert user.email != "contested@example.com"


class TestWhatRecoveryRevokes:
    """A stolen session can stage an attacker's address, and the notice sent to
    the old one tells its owner to change their password. That instruction has
    to *work*: an already-mailed link that still moves the account afterwards
    turns the warning into a countdown."""

    async def test_a_password_change_invalidates_an_outstanding_link(self, db):
        from app.core.security import get_password_hash

        # A real hash, because this one is verified rather than merely replaced.
        user = await _user(db, hashed_password=get_password_hash("secret"))
        service = UserService(db)
        _, token = await service.update_current(user, UserUpdate(email="attacker@example.com"))
        assert token is not None

        await service.change_password(user, current_password="secret", new_password="newsecret")

        with pytest.raises(AuthenticationError):
            await service.confirm_email_change(token)

    async def test_a_password_reset_invalidates_it_and_clears_the_staging(self, db):
        user = await _user(db)
        service = UserService(db)
        _, token = await service.update_current(user, UserUpdate(email="attacker@example.com"))
        assert token is not None
        issued = await service.issue_password_reset_token(user.email)
        assert issued is not None

        await service.confirm_password_reset(issued[1], "newsecret")

        await db.refresh(user)
        assert user.pending_email is None
        with pytest.raises(AuthenticationError):
            await service.confirm_email_change(token)

    async def test_an_administrator_repairing_the_address_clears_the_staging(self, db):
        """The admin path writes `users.email` directly and bumps no credential
        version, so this is the only thing that revokes the staged change."""
        user = await _user(db)
        admin = await _user(db, is_app_admin=True)
        service = UserService(db)
        _, token = await service.update_current(user, UserUpdate(email="attacker@example.com"))
        assert token is not None

        await service.admin_update(
            user.id, UserUpdate(email="repaired@example.com"), acting_admin_id=admin.id
        )

        await db.refresh(user)
        assert user.pending_email is None
        with pytest.raises(AuthenticationError):
            await service.confirm_email_change(token)


class TestWhatOneAccountCanSend:
    """`PATCH /users/me` is a console route and console routes are unmetered,
    registration is open by default, and the destination is the caller's to
    name - so the mail this deployment sends on that say needs a bound of its
    own."""

    async def test_asking_again_for_the_address_already_staged_sends_nothing(self, db):
        user = await _user(db)
        service = UserService(db)
        await service.update_current(user, UserUpdate(email="new@example.com"))

        updated, token = await service.update_current(user, UserUpdate(email="new@example.com"))

        assert token is None
        assert updated.pending_email == "new@example.com"

    async def test_a_patch_of_another_field_does_not_resend_the_verification(self, db):
        """The response carries `pending_email` for as long as the change is
        outstanding, so a save of the display name must not mint a second
        token."""
        user = await _user(db)
        service = UserService(db)
        await service.update_current(user, UserUpdate(email="new@example.com"))

        updated, token = await service.update_current(user, UserUpdate(full_name="Renamed"))

        assert token is None
        assert updated.pending_email == "new@example.com"

    async def test_too_many_distinct_addresses_are_refused(self, db, monkeypatch):
        user = await _user(db)
        service = UserService(db)
        monkeypatch.setattr(
            rate_limit,
            "consume",
            AsyncMock(return_value=rate_limit.Decision(allowed=False, retry_after_seconds=3600)),
        )

        with pytest.raises(RateLimitError) as refusal:
            await service.update_current(user, UserUpdate(email="flood@example.com"))

        assert refusal.value.details["retry_after_seconds"] == 3600
        await db.refresh(user)
        assert user.pending_email is None


class TestTheLosingSideOfAContestedAddress:
    async def test_it_is_a_conflict_rather_than_an_unhandled_constraint(self, db, monkeypatch):
        """Two accounts staging one address each lock their own row, so neither
        read sees the other and the unique index decides. The loser owes a 409
        naming the address, not an `IntegrityError` escaping as a 500."""
        other = await _user(db, email="contested@example.com")
        user = await _user(db)
        service = UserService(db)
        # The lookup is made to miss the way a concurrent transaction's
        # uncommitted insert would, so the staging and the confirmation both
        # reach the unique index rather than the pre-check.
        monkeypatch.setattr(user_module.user_repo, "get_by_email", AsyncMock(return_value=None))
        _, token = await service.update_current(user, UserUpdate(email=other.email))
        assert token is not None

        with pytest.raises(AlreadyExistsError) as refusal:
            await service.confirm_email_change(token)

        assert refusal.value.details["email"] == other.email
