"""Field-level Fernet encryption for RAG connector configuration.

**Not the vault, and not a second option.** Provider credentials, channel bot
tokens, MCP credentials and organization secrets all go through
:mod:`app.core.vault`, whose envelope is derived from the owner's id so a
ciphertext lifted into another tenant's row fails to unwrap. This module has no
such property: one deployment-wide key encrypts everything, which is exactly the
weakness the vault exists to remove.

It survives for one caller — :mod:`app.services.sync_source`, the template's RAG
connector configs — and only because ``sync_sources.organization_id`` is
nullable and the CLI creates rows without one. There is no owner to bind a
ciphertext to, so converging it means making that column NOT NULL and giving the
CLI an organization first. That is a change to template-inherited code with its
own migration, and doing it here would have hidden it inside a security change.

Do not use this for anything new. If you are storing a secret, you want
:func:`app.core.secret_kinds.seal_secret`.
"""

import base64
import hashlib

from cryptography.fernet import Fernet

_PREFIX = "enc:"


def _fernet(raw_key: str) -> Fernet:
    """Derive a valid 32-byte Fernet key from any string via SHA-256."""
    digest = hashlib.sha256(raw_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_value(plaintext: str, raw_key: str) -> str:
    """Encrypt *plaintext* and return a prefixed ciphertext string."""
    token = _fernet(raw_key).encrypt(plaintext.encode()).decode()
    return f"{_PREFIX}{token}"


def decrypt_value(value: str, raw_key: str) -> str:
    """Decrypt a prefixed ciphertext; return the string unchanged if not encrypted."""
    if not value.startswith(_PREFIX):
        return value
    return _fernet(raw_key).decrypt(value[len(_PREFIX) :].encode()).decode()


def is_encrypted(value: object) -> bool:
    """Return True if *value* is a string produced by :func:`encrypt_value`."""
    return isinstance(value, str) and value.startswith(_PREFIX)
