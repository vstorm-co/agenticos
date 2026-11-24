"""Two-factor authentication for console sign-in, via TOTP.

Enrolment is three steps: begin setup (a secret is sealed under the user's
own vault scope and the provisioning URI is shown once), enable (the
authenticator proves it can produce a code, and ten single-use recovery
codes are handed back once), and from then on every password sign-in stops
at a second step until the code - or a recovery code - is given.

The secret lives sealed (see `app/core/vault.py`): a database read alone
never yields it, and it cannot be unwrapped for another user. Recovery codes
are stored as SHA-256 digests, the way refresh tokens are stored as theirs.
A password change bumps `credential_version`, which is what invalidates an
MFA challenge minted before it - the same claim the refresh gate uses.
"""

import hmac
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthenticationError, BadRequestError
from app.core.totp import (
    generate_recovery_codes,
    generate_secret,
    hash_recovery_code,
    provisioning_uri,
    verify_code,
)
from app.core.vault import VaultScope, seal, unseal
from app.db.models.user import User
from app.repositories import user as user_repo

_ISSUER = "AgenticOS"


class MfaService:
    """Enrolment, disablement and challenge verification for one account."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def is_enabled(self, user: User) -> bool:
        """Whether this account's sign-in stops at a second factor."""
        return user.totp_enabled

    async def begin_setup(self, user: User) -> tuple[str, str]:
        """Start enrolment: seal a fresh secret, return its URI and the secret.

        The secret is returned once, so the account can type it into the
        authenticator when scanning is not possible. It is stored before it
        is proved - `totp_enabled` stays off until `enable` sees a good code -
        so a setup abandoned halfway changes nothing about sign-in, and
        starting again replaces the pending secret rather than adding a
        second one. Recovery codes from any earlier enrolment are cleared
        with it: they belonged to a secret that no longer exists.
        """
        if user.totp_enabled:
            raise BadRequestError(
                message="Two-factor authentication is already enabled",
                details={"action": "disable it first to enrol a new authenticator"},
            )
        secret = generate_secret()
        sealed = seal(secret, scope=VaultScope.user(user.id))
        await user_repo.update(
            self.db,
            db_user=user,
            update_data={
                "totp_secret_encrypted": sealed.ciphertext,
                "totp_key_version": sealed.key_version,
                "totp_enabled": False,
                "totp_recovery_hashes": None,
            },
        )
        return provisioning_uri(secret, account_name=user.email, issuer=_ISSUER), secret

    async def enable(self, user: User, code: str) -> list[str]:
        """Prove the enrolled authenticator and switch the second factor on.

        Returns the ten recovery codes, once - they are the way back in when
        the authenticator is lost, so they are shown at enrolment and never
        again. Only their digests are stored.
        """
        secret = self._pending_secret(user)
        counter = verify_code(secret, code)
        if counter is None:
            raise AuthenticationError(
                message="That code did not match - try the code your authenticator shows now"
            )
        codes = generate_recovery_codes()
        await user_repo.update(
            self.db,
            db_user=user,
            update_data={
                "totp_enabled": True,
                "totp_last_counter": counter,
                "totp_recovery_hashes": [hash_recovery_code(code) for code in codes],
            },
        )
        await self._audit(user, "mfa.enabled")
        return codes

    async def disable(self, user: User, code: str) -> None:
        """Switch the second factor off, proved by a code from the account.

        A code is required rather than the session alone: a session left open
        on a shared screen must not be able to strip the factor that protects
        the next sign-in. A recovery code proves it too - that is the way back
        in when the authenticator is already lost.
        """
        if not user.totp_enabled:
            raise BadRequestError(message="Two-factor authentication is not enabled")
        if not await self.verify_challenge(user, code):
            raise AuthenticationError(
                message="That code did not match - try the code your authenticator shows now"
            )
        await user_repo.update(
            self.db,
            db_user=user,
            update_data={
                "totp_secret_encrypted": None,
                "totp_key_version": None,
                "totp_enabled": False,
                "totp_recovery_hashes": None,
            },
        )
        await self._audit(user, "mfa.disabled")

    async def regenerate_recovery_codes(self, user: User, code: str) -> list[str]:
        """Replace the recovery codes, proved by a code from the account.

        The old set stops working the moment the new one is stored - a code
        photographed or copied earlier is not a spare way in afterwards.
        Returns the new codes, once.
        """
        if not user.totp_enabled:
            raise BadRequestError(message="Two-factor authentication is not enabled")
        if not await self.verify_challenge(user, code):
            raise AuthenticationError(
                message="That code did not match - try the code your authenticator shows now"
            )
        codes = generate_recovery_codes()
        await user_repo.update(
            self.db,
            db_user=user,
            update_data={
                "totp_recovery_hashes": [hash_recovery_code(code) for code in codes],
            },
        )
        await self._audit(user, "mfa.recovery_codes_regenerated")
        return codes

    async def verify_challenge(self, user: User, code: str) -> bool:
        """Whether `code` completes this account's second step.

        A recovery code is tried first: it is single-use, so a match consumes
        it - the digest leaves the stored list, and the spend is audited, so
        the account's owner can see a code was used. Anything else must be
        the authenticator's current code. A code that matches neither is
        simply false; the route decides what that refusal says.
        """
        if not user.totp_enabled or user.totp_secret_encrypted is None:
            return False
        candidate = hash_recovery_code(code)
        stored = user.totp_recovery_hashes or []
        if any(hmac.compare_digest(digest, candidate) for digest in stored):
            remaining = await user_repo.consume_totp_recovery_hash(self.db, user.id, candidate)
            if remaining is not None:
                user.totp_recovery_hashes = remaining
                await self._audit(user, "mfa.recovery_code_used", {"remaining": len(remaining)})
                return True
        counter = verify_code(self._unseal(user), code)
        if counter is None:
            return False
        claimed = await user_repo.claim_totp_counter(self.db, user.id, counter)
        if claimed:
            user.totp_last_counter = counter
        return claimed

    def _pending_secret(self, user: User) -> str:
        """The enrolled-but-unproved secret, or the refusal that none exists."""
        if user.totp_enabled:
            raise BadRequestError(
                message="Two-factor authentication is already enabled",
                details={"action": "disable it first to enrol a new authenticator"},
            )
        if user.totp_secret_encrypted is None:
            raise BadRequestError(
                message="Set up two-factor authentication first",
                details={"action": "begin setup to enrol an authenticator"},
            )
        return self._unseal(user)

    def _unseal(self, user: User) -> str:
        """The account's TOTP secret, unwrapped from its vault envelope."""
        assert user.totp_secret_encrypted is not None
        return unseal(
            user.totp_secret_encrypted,
            scope=VaultScope.user(user.id),
            key_version=user.totp_key_version or 1,
        )

    async def _audit(self, user: User, action: str, details: dict[str, Any] | None = None) -> None:
        """The MFA change, on the trail - enrolment and recovery-code spends
        are the events an account's owner needs to be able to see."""
        await record_audit(
            self.db,
            actor_user_id=user.id,
            action=action,
            target_type="user",
            target_id=str(user.id),
            details=details or {},
        )
