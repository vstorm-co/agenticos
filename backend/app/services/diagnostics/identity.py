"""Closed diagnostic identity and signatures; no deployment or user names."""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.schemas.diagnostics import Event


@dataclass(frozen=True)
class Identity:
    seed: bytes = field(repr=False)

    def _derive(self, purpose: bytes) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=purpose).derive(self.seed)

    @property
    def key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(self._derive(b"diagnostics/signing/v1"))

    @property
    def public_key(self) -> str:
        return base64.b64encode(self.key.public_key().public_bytes_raw()).decode()

    @property
    def instance_id(self) -> str:
        return hashlib.sha256(self.key.public_key().public_bytes_raw()).hexdigest()

    def user_id(self, user: UUID) -> str:
        return hmac.digest(self._derive(b"diagnostics/users/v1"), user.bytes, "sha256").hex()

    def event_id(self, slot: str) -> str:
        return hmac.digest(self._derive(b"diagnostics/events/v1"), slot.encode(), "sha256").hex()[
            :32
        ]

    def sign(self, event: Event) -> str:
        body = json.dumps(
            event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return base64.b64encode(self.key.sign(body)).decode()
