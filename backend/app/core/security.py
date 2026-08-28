"""Security utilities for JWT authentication."""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


def encode_untrusted(value: str) -> bytes:
    """UTF-8 bytes for an attacker-controlled string, never raising on a surrogate.

    A webhook body carries `{"token": "\\ud800"}` through `json.loads` as a lone
    surrogate, and a bare `str.encode()` on it raises `UnicodeEncodeError` - a 500,
    and exactly the log-flooding crash a credential check is meant to refuse
    quietly (#33). `surrogatepass` turns it into bytes that cannot match a real
    secret, so the check returns a clean non-match. A string with no surrogate
    encodes byte-for-byte as it did before.
    """
    return value.encode("utf-8", "surrogatepass")


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
    *,
    act: str | None = None,
) -> str:
    """Create a JWT access token.

    `act` is the actor behind the subject when the two differ - an administrator
    impersonating another account. It is carried as its own claim so a request
    made with the token is attributable to the person who is really acting, not
    only to the account they are acting as (#943). Omitted from the payload when
    unset, so an ordinary token is byte-for-byte what it was.
    """
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: dict[str, Any] = {"exp": expire, "sub": str(subject), "type": "access"}
    if act is not None:
        to_encode["act"] = str(act)
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT refresh token."""
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> dict[str, Any] | None:
    """Verify a JWT token and return payload."""
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except jwt.PyJWTError:
        return None


def create_password_reset_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
) -> str:
    """Single-use JWT for password reset.

    Short-lived (1h default). The `type` claim distinguishes it from access /
    refresh / magic-link tokens - a stolen reset token can't be used as an
    access token.
    """
    expire = datetime.now(UTC) + (expires_delta or timedelta(hours=1))
    to_encode = {"exp": expire, "sub": str(subject), "type": "password_reset"}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_magic_link_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
    return_to: str | None = None,
) -> str:
    """Sign-in-by-email JWT. Short-lived (15 min default).

    `return_to` rides in the token because a magic link is followed from an
    email - a different tab, often a different application, sometimes a
    different browser - so the tab-local store the OAuth round trip uses is
    empty by construction there (#1214). Signed, so the path cannot be edited
    between the mint and the landing; validated before it gets here, by
    `MagicLinkRequest`, so nothing unchecked is ever put in a token.
    """
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=15))
    to_encode: dict[str, Any] = {"exp": expire, "sub": str(subject), "type": "magic_link"}
    if return_to is not None:
        to_encode["rt"] = return_to
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_special_token(token: str, expected_type: str) -> dict[str, Any] | None:
    """Verify a non-access JWT (password_reset, magic_link) and require a
    specific `type` claim. Returns payload on success, None otherwise.
    """
    payload = verify_token(token)
    if payload is None:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload


# bcrypt only ever uses the first 72 bytes of a password, and bcrypt 5.0 raises
# rather than truncating silently. Both helpers truncate to the same 72 bytes, so
# hashing and verifying agree - and an overlong password submitted at the login
# form (a `UserCreate.password` of up to 128 characters can exceed 72 bytes once
# encoded, and an unknown account still runs bcrypt against the dummy hash) is an
# authentication failure rather than an unauthenticated 500 (#947).
_BCRYPT_MAX_BYTES = 72


def _bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(
        _bcrypt_bytes(plain_password),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return bcrypt.hashpw(
        _bcrypt_bytes(password),
        bcrypt.gensalt(),
    ).decode("utf-8")
