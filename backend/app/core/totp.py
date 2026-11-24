"""Time-based one-time passwords (RFC 6238) for console sign-in.

No third-party dependency: the algorithm is HMAC-SHA1 over a time counter,
and the standard library carries all of it. The secret is a 160-bit value in
base32 - the shape every authenticator app expects - and the code is six
digits over a 30-second step, the default every authenticator app assumes.

Verification accepts the step before and after the current one, so a code
typed as the step turns over still lands. Anything further out is refused:
a wider window is a wider guessable surface, and the authenticator's own
clock is the thing to fix when codes keep missing.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

_STEP_SECONDS = 30
_DIGITS = 6
_WINDOW_STEPS = 1

# Recovery codes are the way back in when the authenticator is lost. Ten
# single-use codes, each eight characters from an alphabet with the
# lookalikes removed (no 0/O, 1/I/l), grouped for typing: `ABCD-EFGH`.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_RECOVERY_CODE_GROUPS = (4, 4)
_RECOVERY_CODE_COUNT = 10


def generate_secret() -> str:
    """A fresh 160-bit secret, base32, without padding - the authenticator form."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, counter: int, *, digits: int = _DIGITS) -> str:
    """The code for one counter value: HMAC-SHA1, dynamic truncation (RFC 4226)."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def code_now(secret: str, *, at: float | None = None) -> str:
    """The code an authenticator shows right now, for tests and the setup check."""
    moment = at if at is not None else time.time()
    return _code(secret, int(moment // _STEP_SECONDS))


def verify_code(secret: str, code: str, *, at: float | None = None) -> int | None:
    """Return the counter matched by `code`, or None if no step matches.

    The comparison is constant-time, and a code that is not six digits cannot
    match - it is refused before any HMAC runs, so a longer guess is not a
    slower path to the same answer.
    """
    candidate = code.strip()
    if len(candidate) != _DIGITS or not candidate.isdigit():
        return None
    moment = at if at is not None else time.time()
    current = int(moment // _STEP_SECONDS)
    for step in range(current - _WINDOW_STEPS, current + _WINDOW_STEPS + 1):
        if hmac.compare_digest(_code(secret, step), candidate):
            return step
    return None


def provisioning_uri(secret: str, *, account_name: str, issuer: str) -> str:
    """The `otpauth://` URI an authenticator app scans, or the account types in.

    The label carries the issuer so two deployments' entries do not collide
    in the app's list, and the parameters name the defaults explicitly - an
    app that assumed otherwise would enrol a secret it then reads wrong.
    """
    label = quote(f"{issuer}:{account_name}", safe=":")
    params = (
        f"secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={_DIGITS}&period={_STEP_SECONDS}"
    )
    return f"otpauth://totp/{label}?{params}"


def generate_recovery_codes(*, count: int = _RECOVERY_CODE_COUNT) -> list[str]:
    """Fresh single-use recovery codes, each returned once, in full."""
    codes = set()
    while len(codes) < count:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(sum(_RECOVERY_CODE_GROUPS)))
        groups, start = [], 0
        for size in _RECOVERY_CODE_GROUPS:
            groups.append(raw[start : start + size])
            start += size
        codes.add("-".join(groups))
    return sorted(codes)


def hash_recovery_code(code: str) -> str:
    """The stored form of a recovery code: a SHA-256 hex digest, never the code.

    Codes are compared by their digest, the way refresh tokens are compared
    by theirs - a database read alone never yields a way back in. Dashes,
    spaces and case are ignored, so a code typed without its dash, or in
    lower case, still matches the one that was issued.
    """
    normalised = code.strip().upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
