"""Tests for security module."""

from datetime import timedelta
from uuid import uuid4

from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    read_uuid_claim,
    verify_password,
    verify_token,
)


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password(self):
        """Test password hashing."""
        password = "mysecretpassword"
        hashed = get_password_hash(password)

        assert hashed != password
        assert len(hashed) > 0
        assert hashed.startswith("$2")  # bcrypt prefix

    def test_verify_password_correct(self):
        """Test verifying correct password."""
        password = "mysecretpassword"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        password = "mysecretpassword"
        wrong_password = "wrongpassword"
        hashed = get_password_hash(password)

        assert verify_password(wrong_password, hashed) is False

    def test_a_password_over_bcrypts_limit_hashes_and_verifies_rather_than_raising(self):
        """bcrypt 5.0 raises past 72 bytes; both helpers truncate to it, so an
        overlong password is an ordinary credential (and a mismatch stays a
        mismatch) instead of an unauthenticated 500 (#947)."""
        overlong = "p" * 200
        hashed = get_password_hash(overlong)

        assert verify_password(overlong, hashed) is True
        # Agrees only on the first 72 bytes, which is all bcrypt reads.
        assert verify_password("p" * 72, hashed) is True
        assert verify_password("q" * 200, hashed) is False


class TestAccessToken:
    """Tests for access token functions."""

    def test_create_access_token(self):
        """Test creating access token."""
        subject = "user123"
        token = create_access_token(subject)

        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_access_token_with_expires_delta(self):
        """Test creating access token with custom expiration."""
        subject = "user123"
        expires = timedelta(hours=2)
        token = create_access_token(subject, expires_delta=expires)

        assert isinstance(token, str)
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == subject
        assert payload["type"] == "access"

    def test_verify_access_token(self):
        """Test verifying access token."""
        subject = "user123"
        token = create_access_token(subject)
        payload = verify_token(token)

        assert payload is not None
        assert payload["sub"] == subject
        assert payload["type"] == "access"

    def test_an_ordinary_token_carries_no_actor_claim(self):
        """The `act` claim is absent unless someone is impersonating, so an
        ordinary token is exactly what it was before #943."""
        payload = verify_token(create_access_token("user123"))

        assert payload is not None
        assert "act" not in payload

    def test_an_impersonation_token_names_the_actor_behind_the_subject(self):
        """The subject is the account being acted as; `act` is who is acting."""
        payload = verify_token(create_access_token("target-user", act="admin-user"))

        assert payload is not None
        assert payload["sub"] == "target-user"
        assert payload["act"] == "admin-user"

    def test_verify_invalid_token(self):
        """Test verifying invalid token."""
        payload = verify_token("invalid.token.here")

        assert payload is None

    def test_verify_expired_token(self):
        """Test verifying expired token."""
        subject = "user123"
        # Create token that expires immediately
        token = create_access_token(subject, expires_delta=timedelta(seconds=-1))
        payload = verify_token(token)

        assert payload is None

    def test_an_expired_token_still_decodes_when_expiry_is_not_verified(self):
        """`verify_exp=False` decodes a signature-valid but expired token - the
        one thing an open chat socket needs, since it outlives its access token's
        lifetime and must judge revocation from state, not `exp` (#1437)."""
        token = create_access_token("user123", expires_delta=timedelta(seconds=-1))

        payload = verify_token(token, verify_exp=False)

        assert payload is not None
        assert payload["sub"] == "user123"

    def test_a_forged_token_is_refused_even_when_expiry_is_not_verified(self):
        """`verify_exp=False` relaxes expiry alone; the signature is still
        checked, so a token this deployment did not sign is still refused."""
        assert verify_token("not.a.real.token", verify_exp=False) is None


class TestReadUuidClaim:
    """The one lenient reader both impersonation and ordinary-session binding use."""

    def test_a_present_uuid_claim_is_parsed(self):
        session_id = uuid4()
        assert read_uuid_claim({"sid": str(session_id)}, "sid") == session_id

    def test_an_absent_claim_is_none(self):
        assert read_uuid_claim({"sub": "u"}, "sid") is None

    def test_an_empty_claim_is_none(self):
        assert read_uuid_claim({"sid": ""}, "sid") is None

    def test_a_malformed_claim_is_none_not_a_refusal(self):
        """The token is signed, so a value it cannot parse is one this code never
        wrote - read as no claim rather than raising (#943)."""
        assert read_uuid_claim({"sid": "not-a-uuid"}, "sid") is None


class TestRefreshToken:
    """Tests for refresh token functions."""

    def test_create_refresh_token(self):
        """Test creating refresh token."""
        subject = "user123"
        token = create_refresh_token(subject)

        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token_with_expires_delta(self):
        """Test creating refresh token with custom expiration."""
        subject = "user123"
        expires = timedelta(days=7)
        token = create_refresh_token(subject, expires_delta=expires)

        assert isinstance(token, str)
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == subject
        assert payload["type"] == "refresh"

    def test_verify_refresh_token(self):
        """Test verifying refresh token."""
        subject = "user123"
        token = create_refresh_token(subject)
        payload = verify_token(token)

        assert payload is not None
        assert payload["sub"] == subject
        assert payload["type"] == "refresh"

    def test_two_refresh_tokens_for_one_subject_are_unique(self):
        """A random `jti` keeps two tokens minted for one subject in the same
        second from being byte-identical: their hashes would otherwise collide
        into two session rows under one hash, and the next refresh's lookup raises
        instead of resolving (#1501)."""
        first = create_refresh_token("user123")
        second = create_refresh_token("user123")

        assert first != second
        payload = verify_token(first)
        assert payload is not None
        assert payload["jti"]
