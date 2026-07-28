"""The secret vault - envelope encryption for everything the platform stores.

Every provider key, channel bot token, MCP credential and organization secret
passes through here, and there is deliberately no second mechanism. Two
properties matter and both come from the envelope:

*Binding to an owner.* Each secret is sealed with its own random data key, which
is itself sealed with a key derived from the master key **and the scope that
owns it** - an organization, or the member a personal connection belongs to. A
ciphertext therefore cannot be moved between owners: even with database access,
a row copied from org A into org B fails to unwrap. A single global Fernet key
- what this codebase used for channel tokens and MCP tokens - gives no such
guarantee, which is the whole reason it is gone.

*Rotatable master key.* The master key never encrypts payloads directly, only
data keys, so rotating it means re-wrapping one small blob per secret rather
than re-encrypting every value. ``key_version`` records which master key sealed
a given envelope, which is what makes a staged rotation possible at all.

Nothing here decides *who* may read a secret; that is the permission layer's
job (``connections:manage``). This module only guarantees that a secret at rest
is unreadable without the master key and unusable outside the scope it was
sealed for.

This module handles opaque strings. The typed shapes a secret can take - an API
key, an AWS key pair, a service account - live in :mod:`app.core.secret_kinds`,
which seals through here.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.exceptions import BadRequestError

# Bump when the envelope format changes in a way older readers cannot parse.
ENVELOPE_VERSION = 1


class VaultScopeKind(StrEnum):
    """What kind of principal a secret is bound to.

    Part of the key derivation input, so it is also what stops an organization
    envelope being unwrapped as a personal one (or the reverse) if the two ids
    ever collide.
    """

    ORGANIZATION = "org"
    USER = "user"


@dataclass(frozen=True)
class VaultScope:
    """Who a sealed secret belongs to.

    Almost everything is owned by an organization; the exception is a member's
    personal MCP connection, which belongs to them and to no tenant - the row
    has no ``organization_id`` at all, and a member may be in several
    organizations, so binding it to whichever one happened to be active when
    they added it would make the token unreadable after they switch.
    """

    kind: VaultScopeKind
    subject_id: UUID

    @classmethod
    def organization(cls, organization_id: UUID) -> VaultScope:
        return cls(kind=VaultScopeKind.ORGANIZATION, subject_id=organization_id)

    @classmethod
    def user(cls, user_id: UUID) -> VaultScope:
        return cls(kind=VaultScopeKind.USER, subject_id=user_id)

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.subject_id}"


@dataclass(frozen=True)
class SealedSecret:
    """An encrypted secret plus the metadata needed to unseal and display it.

    ``hint`` is a four-character fragment of the plaintext. It is stored in the
    clear on purpose: operators need to tell two keys apart in a dropdown, and
    four characters of a provider key identify it to its owner without being
    useful to anyone else.
    """

    ciphertext: str
    hint: str
    key_version: int


def _master_key() -> str:
    """The deployment's master key.

    Falls back to ``SECRET_KEY`` so a fresh checkout runs without extra setup;
    production deployments set ``VAULT_MASTER_KEY`` explicitly, and the config
    validator refuses the default ``SECRET_KEY`` outside development.
    """
    configured = getattr(settings, "VAULT_MASTER_KEY", "") or ""
    return configured or settings.SECRET_KEY


def _wrapping_key(scope: VaultScope, key_version: int) -> Fernet:
    """Derive the key that seals a data key, bound to one owner.

    The scope is part of the derivation input, which is what makes a ciphertext
    non-portable between tenants.
    """
    material = f"{_master_key()}|{scope}|v{key_version}".encode()
    digest = hashlib.sha256(material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(plaintext: str, *, scope: VaultScope, key_version: int = 1) -> SealedSecret:
    """Encrypt a secret for one owner.

    Raises:
        BadRequestError: If the secret is empty. An empty credential is always a
            mistake, and storing one produces a key that fails much later at the
            provider with a far less obvious message. A component that genuinely
            needs no credential - a local model endpoint - is stored as
            :data:`app.core.secret_kinds.SecretKind.NONE` with no envelope at
            all, rather than as an envelope around nothing.
    """
    if not plaintext:
        raise BadRequestError(message="Cannot store an empty secret")

    data_key = Fernet.generate_key()
    payload = Fernet(data_key).encrypt(plaintext.encode())
    wrapped_key = _wrapping_key(scope, key_version).encrypt(data_key)

    envelope = json.dumps(
        {
            "v": ENVELOPE_VERSION,
            "k": wrapped_key.decode(),
            "p": payload.decode(),
        },
        separators=(",", ":"),
    )
    return SealedSecret(
        ciphertext=envelope,
        hint=plaintext[-4:],
        key_version=key_version,
    )


def unseal(ciphertext: str, *, scope: VaultScope, key_version: int = 1) -> str:
    """Decrypt a secret sealed for this owner.

    Raises:
        BadRequestError: If the envelope is malformed, or was sealed with a
            different master key or for a different owner. All three surface the
            same message - distinguishing them would tell an attacker which of
            the three they got wrong.
    """
    try:
        envelope = json.loads(ciphertext)
        wrapped_key = envelope["k"].encode()
        payload = envelope["p"].encode()
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as exc:
        raise BadRequestError(message="Stored secret is malformed") from exc

    try:
        data_key = _wrapping_key(scope, key_version).decrypt(wrapped_key)
        return Fernet(data_key).decrypt(payload).decode()
    except (InvalidToken, ValueError) as exc:
        raise BadRequestError(
            message="Failed to decrypt secret - wrong master key or owner"
        ) from exc


def rewrap(
    ciphertext: str,
    *,
    scope: VaultScope,
    from_version: int,
    to_version: int,
) -> str:
    """Move an envelope to a new master-key version without touching the payload.

    Only the wrapped data key is re-sealed, so rotating the master key costs one
    small operation per secret instead of a full re-encryption.
    """
    try:
        envelope = json.loads(ciphertext)
        wrapped_key = envelope["k"].encode()
    # The same set unseal() catches. A rotation job walks every row, so it is
    # exactly where an envelope with a non-string key would surface - and it
    # should surface as "malformed", not as a raw AttributeError from .encode().
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as exc:
        raise BadRequestError(message="Stored secret is malformed") from exc

    try:
        data_key = _wrapping_key(scope, from_version).decrypt(wrapped_key)
    except InvalidToken as exc:
        raise BadRequestError(message="Failed to unwrap secret for rotation") from exc

    envelope["k"] = _wrapping_key(scope, to_version).encrypt(data_key).decode()
    return json.dumps(envelope, separators=(",", ":"))


def generate_master_key() -> str:
    """A fresh master key, for ``VAULT_MASTER_KEY`` in a new deployment."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()
