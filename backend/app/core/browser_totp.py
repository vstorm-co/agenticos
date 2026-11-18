"""Generate a selected browser code only inside the confirmed writer."""

import base64
import hashlib
import hmac
import math
import struct
from dataclasses import dataclass

from pydantic import SecretStr

from app.core.secret_kinds import BrowserTotp


@dataclass(frozen=True)
class BrowserCode:
    value: SecretStr
    valid_until: float


def browser_code(config: BrowserTotp, *, at: float) -> BrowserCode:
    """RFC 6238 at one trusted clock instant; neither a seed nor a code is logged."""
    if not math.isfinite(at) or at < 0:
        raise ValueError("A browser code needs a valid current time")
    counter = math.floor(at / config.period_seconds)
    if counter >= 2**64:
        raise ValueError("The browser code counter is outside its supported range")
    encoded = config.seed.get_secret_value()
    key = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    algorithm = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}[
        config.algorithm
    ]
    digest = hmac.new(key, struct.pack(">Q", counter), algorithm).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (
        10**config.digits
    )
    return BrowserCode(
        value=SecretStr(str(number).zfill(config.digits)),
        valid_until=float((counter + 1) * config.period_seconds),
    )
