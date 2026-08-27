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
than re-encrypting every value. `key_version` records which master key sealed
a given envelope, and `VAULT_MASTER_KEYS` maps each version still in use to
its key - which is what makes a staged rotation possible at all: configure the
old and the new key side by side, run `agenticos cmd vault-rotate`, then drop
the old one.

Nothing here decides *who* may read a secret; that is the permission layer's
job (`connections:manage`). This module only guarantees that a secret at rest
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
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConfigurationError

# Bump when the envelope format changes in a way older readers cannot parse.
# Version 1 derived its wrapping key with a bare SHA-256; version 2 uses
# HKDF-SHA256. Both stay readable - the envelope records which sealed it.
ENVELOPE_VERSION = 2


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
    has no `organization_id` at all, and a member may be in several
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

    `hint` is a four-character fragment of the plaintext. It is stored in the
    clear on purpose: operators need to tell two keys apart in a dropdown, and
    four characters of a provider key identify it to its owner without being
    useful to anyone else.
    """

    ciphertext: str
    hint: str
    key_version: int


def _configured_master_keys() -> dict[int, str]:
    """Every master key this deployment may unwrap with, by version.

    `VAULT_MASTER_KEYS` is the explicit form and, when set, the whole truth.
    The single `VAULT_MASTER_KEY` is shorthand for version 1, falling back to
    `SECRET_KEY` so a fresh checkout runs without extra setup - the config
    validator refuses that fallback outside local/development.
    """
    if settings.VAULT_MASTER_KEYS:
        return settings.VAULT_MASTER_KEYS
    return {1: settings.VAULT_MASTER_KEY or settings.SECRET_KEY}


def current_key_version() -> int:
    """The version new secrets are sealed under - the highest one configured."""
    return max(_configured_master_keys())


def _master_key(key_version: int) -> str:
    """The master key that sealed envelopes at this version.

    Raises:
        ConfigurationError: If no key is configured for the version. A sealed
            row names the version that wrapped it, so this means the operator
            dropped a key from `VAULT_MASTER_KEYS` before `vault-rotate`
            finished moving every row off it.
    """
    key = _configured_master_keys().get(key_version)
    if key is None:
        raise ConfigurationError(
            message=f"No master key configured for version {key_version} - "
            "restore it in VAULT_MASTER_KEYS until vault-rotate has re-wrapped every secret",
            details={"key_version": key_version},
        )
    return key


def _wrapping_key(
    scope: VaultScope, key_version: int, *, envelope_version: int = ENVELOPE_VERSION
) -> Fernet:
    """Derive the key that seals a data key, bound to one owner.

    The scope is part of the derivation input, which is what makes a ciphertext
    non-portable between tenants. Version-1 envelopes derived it with a single
    SHA-256 over the concatenated material; everything sealed since uses
    HKDF-SHA256 with the scope and key version as `info`, because one hash over
    a possibly passphrase-derived value is not a KDF (#8).
    """
    master = _master_key(key_version)
    if envelope_version == 1:
        digest = hashlib.sha256(f"{master}|{scope}|v{key_version}".encode()).digest()
    else:
        digest = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"{scope}|v{key_version}".encode(),
        ).derive(master.encode())
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(plaintext: str, *, scope: VaultScope, key_version: int | None = None) -> SealedSecret:
    """Encrypt a secret for one owner.

    `key_version` defaults to the current master key's version. Passing one
    explicitly is for a row that already carries sibling envelopes: all of a
    row's ciphertexts share one version column, so a new field is sealed at the
    row's recorded version rather than at whatever is current (#552).

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
    if key_version is None:
        key_version = current_key_version()

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


def seal_fields(
    values: dict[str, str], *, scope: VaultScope, key_version: int | None = None
) -> tuple[dict[str, SealedSecret], int]:
    """Seal several fields of one row under a single key version.

    A row with more than one ciphertext column - a bot token and a signing
    secret, an MCP url and an auth token - shares one `key_version`, because
    :func:`rewrap` moves the whole row's wrapped keys together. This is the one
    way to seal such a row: it seals every field at the same version and hands
    that version back to store on the row, so "seal at v2 but record v1" and
    "no version column at all" cannot be written by hand - which is how a rotated
    row became un-openable at more than one model (#552).

    An empty value is skipped rather than sealed - a field a row does not carry is
    absent, not an envelope around nothing, the same rule :func:`seal` enforces -
    so the returned mapping may hold fewer keys than `values`.
    """
    if key_version is None:
        key_version = current_key_version()
    sealed = {
        name: seal(value, scope=scope, key_version=key_version)
        for name, value in values.items()
        if value
    }
    return sealed, key_version


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
        sealed_with = envelope.get("v", 1)
        wrapped_key = envelope["k"].encode()
        payload = envelope["p"].encode()
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as exc:
        raise BadRequestError(message="Stored secret is malformed") from exc
    if sealed_with not in (1, ENVELOPE_VERSION):
        raise BadRequestError(message="Stored secret is malformed")

    try:
        data_key = _wrapping_key(scope, key_version, envelope_version=sealed_with).decrypt(
            wrapped_key
        )
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
    small operation per secret instead of a full re-encryption. The result is
    always in the current envelope format, so rotating also upgrades a version-1
    envelope's derivation to HKDF - which is why `from_version == to_version` is
    legal: it re-wraps in place under the same master key.
    """
    try:
        envelope = json.loads(ciphertext)
        sealed_with = envelope.get("v", 1)
        wrapped_key = envelope["k"].encode()
    # The same set unseal() catches. A rotation job walks every row, so it is
    # exactly where an envelope with a non-string key would surface - and it
    # should surface as "malformed", not as a raw AttributeError from .encode().
    except (json.JSONDecodeError, KeyError, AttributeError, TypeError) as exc:
        raise BadRequestError(message="Stored secret is malformed") from exc
    if sealed_with not in (1, ENVELOPE_VERSION):
        raise BadRequestError(message="Stored secret is malformed")

    try:
        data_key = _wrapping_key(scope, from_version, envelope_version=sealed_with).decrypt(
            wrapped_key
        )
    except InvalidToken as exc:
        raise BadRequestError(message="Failed to unwrap secret for rotation") from exc

    envelope["v"] = ENVELOPE_VERSION
    envelope["k"] = _wrapping_key(scope, to_version).encrypt(data_key).decode()
    return json.dumps(envelope, separators=(",", ":"))


def needs_rotation(ciphertext: str, *, key_version: int) -> bool:
    """Whether a rotation pass should re-wrap this envelope.

    True when the row records a key version other than the current one, or when
    the envelope predates the HKDF derivation. Unparsable ciphertext also
    answers True, so the sweep reaches :func:`rewrap` and fails loudly there
    instead of silently skipping a row it cannot read.
    """
    if key_version != current_key_version():
        return True
    try:
        envelope = json.loads(ciphertext)
        return envelope.get("v", 1) != ENVELOPE_VERSION
    except (json.JSONDecodeError, AttributeError):
        return True


def generate_master_key() -> str:
    """A fresh master key, for `VAULT_MASTER_KEY` in a new deployment."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()
