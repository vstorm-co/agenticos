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

import pytest

from app.core.exceptions import AlreadyExistsError, AuthenticationError
from app.core.security import create_email_change_token
from app.db.models.user import User
from app.schemas.user import UserUpdate
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
        token = create_email_change_token(subject=str(uuid.uuid4()), new_email=user.email)

        with pytest.raises(AuthenticationError):
            await UserService(db).confirm_email_change(token)

    async def test_a_malformed_subject_is_refused(self, db):
        token = create_email_change_token(subject="not-a-uuid", new_email="new@example.com")

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
