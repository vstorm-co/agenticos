"""Tests for the MFA service: enrolment, disablement, recovery codes.

The vault is faked at the seam - `seal` returns the plaintext as the
ciphertext and `unseal` returns it back - so these tests exercise the
service's decisions (when a code proves, when a code is spent, what is
stored) rather than the envelope. The codes themselves are real TOTP codes
from the core module.
"""

import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import AuthenticationError, BadRequestError
from app.core.totp import code_now, hash_recovery_code
from app.core.vault import SealedSecret
from app.services.mfa import MfaService

pytestmark = pytest.mark.anyio


def _next_code(secret):
    return code_now(secret, at=time.time() + 30)


def _user(**overrides):
    state = {
        "id": uuid.uuid4(),
        "email": "ada@example.com",
        "totp_secret_encrypted": None,
        "totp_key_version": None,
        "totp_last_counter": None,
        "totp_enabled": False,
        "totp_recovery_hashes": None,
    }
    state.update(overrides)
    return SimpleNamespace(**state)


async def _apply_update(db, *, db_user, update_data):
    """The repository's half of an update: apply the fields to the row."""
    if not hasattr(db, "users"):
        db.users = {}
    db.users[db_user.id] = db_user
    for field, value in update_data.items():
        setattr(db_user, field, value)
    return db_user


async def _consume_recovery_hash(db, user_id, digest):
    user = db.users[user_id]
    stored = user.totp_recovery_hashes or []
    if digest not in stored:
        return None
    user.totp_recovery_hashes = [value for value in stored if value != digest]
    return user.totp_recovery_hashes


async def _claim_totp_counter(db, user_id, counter):
    user = db.users[user_id]
    if user.totp_last_counter is not None and user.totp_last_counter >= counter:
        return False
    user.totp_last_counter = counter
    return True


@pytest.fixture
def service():
    """An MfaService with the vault and the audit trail faked."""
    with (
        patch(
            "app.services.mfa.seal",
            side_effect=lambda plaintext, *, scope: SealedSecret(
                ciphertext=plaintext, hint=plaintext[-4:], key_version=1
            ),
        ),
        patch(
            "app.services.mfa.unseal",
            side_effect=lambda ciphertext, *, scope, key_version=1: ciphertext,
        ),
        patch(
            "app.services.mfa.user_repo.update",
            new=AsyncMock(side_effect=_apply_update),
        ) as update,
        patch(
            "app.services.mfa.user_repo.consume_totp_recovery_hash",
            new=AsyncMock(side_effect=_consume_recovery_hash),
        ),
        patch(
            "app.services.mfa.user_repo.claim_totp_counter",
            new=AsyncMock(side_effect=_claim_totp_counter),
        ),
        patch("app.services.mfa.record_audit", new=AsyncMock()) as audit,
    ):
        yield MfaService(db=SimpleNamespace(users={})), update, audit


async def _enrolled(service, user):
    """Run setup + enable for `user`; returns the recovery codes."""
    await service.begin_setup(user)
    return await service.enable(user, code_now(user.totp_secret_encrypted))


class TestBeginSetup:
    @pytest.mark.security
    async def test_setup_seals_a_secret_and_shows_how_to_enrol_it(self, service):
        mfa, update, _ = service
        user = _user()

        uri, secret = await mfa.begin_setup(user)

        assert uri.startswith("otpauth://totp/")
        assert f"secret={secret}" in uri
        assert user.totp_secret_encrypted == secret
        assert user.totp_key_version == 1
        assert user.totp_enabled is False
        assert user.totp_recovery_hashes is None
        update.assert_awaited_once()

    @pytest.mark.security
    async def test_setup_again_replaces_a_pending_secret(self, service):
        mfa, _, _ = service
        user = _user()
        _, first = await mfa.begin_setup(user)

        _, second = await mfa.begin_setup(user)

        assert second != first
        assert user.totp_secret_encrypted == second
        assert user.totp_enabled is False

    async def test_setup_refuses_an_account_that_already_has_it(self, service):
        mfa, _, _ = service
        user = _user(totp_enabled=True, totp_secret_encrypted="JBSWY3DPEHPK3PXP")

        with pytest.raises(BadRequestError):
            await mfa.begin_setup(user)


class TestEnable:
    async def test_the_right_code_switches_it_on_and_hands_back_ten_codes(self, service):
        mfa, _, audit = service
        user = _user()
        await mfa.begin_setup(user)

        codes = await mfa.enable(user, code_now(user.totp_secret_encrypted))

        assert len(codes) == 10
        assert user.totp_enabled is True
        assert user.totp_last_counter is not None
        assert user.totp_recovery_hashes == [hash_recovery_code(code) for code in codes]
        assert audit.await_args.kwargs["action"] == "mfa.enabled"

    async def test_the_enable_code_is_rejected_as_a_challenge(self, service):
        mfa, _, _ = service
        user = _user()
        await mfa.begin_setup(user)
        code = code_now(user.totp_secret_encrypted)

        await mfa.enable(user, code)

        assert await mfa.verify_challenge(user, code) is False

    async def test_a_wrong_code_leaves_it_off(self, service):
        mfa, _, audit = service
        user = _user()
        await mfa.begin_setup(user)

        with pytest.raises(AuthenticationError):
            await mfa.enable(user, "000000")

        assert user.totp_enabled is False
        audit.assert_not_awaited()

    async def test_enable_without_setup_is_refused(self, service):
        mfa, _, _ = service
        with pytest.raises(BadRequestError):
            await mfa.enable(_user(), "123456")

    async def test_enable_when_already_on_is_refused(self, service):
        mfa, _, _ = service
        user = _user()
        await _enrolled(mfa, user)

        with pytest.raises(BadRequestError):
            await mfa.enable(user, code_now(user.totp_secret_encrypted))


class TestVerifyChallenge:
    async def test_the_authenticator_code_passes(self, service):
        mfa, _, _ = service
        user = _user()
        await _enrolled(mfa, user)

        assert await mfa.verify_challenge(user, _next_code(user.totp_secret_encrypted)) is True

    async def test_the_same_authenticator_code_fails_the_second_time(self, service):
        mfa, _, _ = service
        user = _user()
        await _enrolled(mfa, user)
        code = _next_code(user.totp_secret_encrypted)

        assert await mfa.verify_challenge(user, code) is True
        assert await mfa.verify_challenge(user, code) is False

    async def test_an_earlier_step_fails_after_a_later_counter_is_claimed(self, service):
        mfa, _, _ = service
        user = _user()
        await _enrolled(mfa, user)
        user.totp_last_counter = None

        with patch(
            "app.services.mfa.verify_code",
            side_effect=lambda secret, code: {"later": 100, "earlier": 99}.get(code),
        ):
            assert await mfa.verify_challenge(user, "later") is True
            assert await mfa.verify_challenge(user, "earlier") is False

        assert user.totp_last_counter == 100

    async def test_a_wrong_code_fails(self, service):
        mfa, _, _ = service
        user = _user()
        await _enrolled(mfa, user)

        assert await mfa.verify_challenge(user, "000000") is False

    async def test_a_recovery_code_passes_once_and_is_then_spent(self, service):
        mfa, _, audit = service
        user = _user()
        codes = await _enrolled(mfa, user)
        spent, *rest = codes

        assert await mfa.verify_challenge(user, spent) is True
        assert user.totp_recovery_hashes == [hash_recovery_code(code) for code in rest]
        assert audit.await_args.kwargs["action"] == "mfa.recovery_code_used"
        assert audit.await_args.kwargs["details"] == {"remaining": 9}
        assert await mfa.verify_challenge(user, spent) is False

    async def test_a_recovery_code_typed_without_its_dash_still_passes(self, service):
        mfa, _, _ = service
        user = _user()
        codes = await _enrolled(mfa, user)

        assert await mfa.verify_challenge(user, codes[0].replace("-", "").lower()) is True

    @pytest.mark.security
    async def test_a_concurrently_spent_recovery_code_cannot_complete_the_challenge(self, service):
        mfa, _, audit = service
        user = _user()
        codes = await _enrolled(mfa, user)
        spent = codes[0]
        audit.reset_mock()

        # This request's user snapshot still includes the hash, but another
        # request won the repository's atomic consume before this one arrived.
        with (
            patch(
                "app.services.mfa.user_repo.consume_totp_recovery_hash",
                new=AsyncMock(return_value=None),
            ) as consume,
            patch("app.services.mfa.user_repo.claim_totp_counter", new=AsyncMock()) as claim,
        ):
            assert await mfa.verify_challenge(user, spent) is False

        consume.assert_awaited_once_with(mfa.db, user.id, hash_recovery_code(spent))
        claim.assert_not_awaited()
        audit.assert_not_awaited()

    async def test_a_challenge_for_an_account_without_it_fails(self, service):
        mfa, _, _ = service
        assert await mfa.verify_challenge(_user(), "123456") is False

    @pytest.mark.security
    async def test_a_challenge_with_no_secret_on_an_enabled_account_fails(self, service):
        mfa, _, _ = service
        user = _user(totp_enabled=True, totp_secret_encrypted=None)
        assert await mfa.verify_challenge(user, "123456") is False


class TestDisable:
    async def test_the_right_code_switches_it_off_and_clears_everything(self, service):
        mfa, _, audit = service
        user = _user()
        await _enrolled(mfa, user)

        await mfa.disable(user, _next_code(user.totp_secret_encrypted))

        assert user.totp_enabled is False
        assert user.totp_secret_encrypted is None
        assert user.totp_key_version is None
        assert user.totp_recovery_hashes is None
        assert audit.await_args.kwargs["action"] == "mfa.disabled"

    async def test_a_recovery_code_switches_it_off_too(self, service):
        mfa, _, _ = service
        user = _user()
        codes = await _enrolled(mfa, user)

        await mfa.disable(user, codes[0])

        assert user.totp_enabled is False

    async def test_a_wrong_code_leaves_it_on(self, service):
        mfa, _, _ = service
        user = _user()
        await _enrolled(mfa, user)

        with pytest.raises(AuthenticationError):
            await mfa.disable(user, "000000")

        assert user.totp_enabled is True

    async def test_disable_when_off_is_refused(self, service):
        mfa, _, _ = service
        with pytest.raises(BadRequestError):
            await mfa.disable(_user(), "123456")


class TestRegenerateRecoveryCodes:
    async def test_new_codes_replace_the_old_set(self, service):
        mfa, _, audit = service
        user = _user()
        old = await _enrolled(mfa, user)

        new = await mfa.regenerate_recovery_codes(user, _next_code(user.totp_secret_encrypted))

        assert len(new) == 10
        assert set(new) != set(old)
        assert audit.await_args.kwargs["action"] == "mfa.recovery_codes_regenerated"
        assert await mfa.verify_challenge(user, old[0]) is False
        assert await mfa.verify_challenge(user, new[0]) is True

    async def test_regenerate_when_off_is_refused(self, service):
        mfa, _, _ = service
        with pytest.raises(BadRequestError):
            await mfa.regenerate_recovery_codes(_user(), "123456")

    async def test_regenerate_with_a_wrong_code_is_refused(self, service):
        mfa, _, _ = service
        user = _user()
        await _enrolled(mfa, user)

        with pytest.raises(AuthenticationError):
            await mfa.regenerate_recovery_codes(user, "000000")


def test_is_enabled_reads_the_flag():
    mfa = MfaService(db=AsyncMock())
    assert mfa.is_enabled(_user(totp_enabled=True)) is True
    assert mfa.is_enabled(_user(totp_enabled=False)) is False
