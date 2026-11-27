"""The proof a passing embedding test leaves, and what a save checks it against.

A test re-embeds stored chunks and says whether the vectors still land where they
were. Saving a change that could move a collection's vector space has to know that
test happened, for exactly those settings, and the server never repeats it: the
test is a user-triggered request that spends the organization's embedding quota, so
the save carries a short-lived signed token instead.

The token is the existing signed-token mechanism (`app.core.security`), bound to a
fingerprint of what was tested - the connection and its address, the key by id and
by `authorization_generation`, the model and the measured width, and every
knowledge base that passed, with the model and width it was probed at. A value
that moves between the test and the save, a key whose value was rotated, or a
knowledge base attached to the connection in the meantime, is a different
fingerprint and the save is refused. It names its caller and organization, so it
cannot be handed to somebody else; it carries neither the address nor the key.
"""

import hashlib
import hmac
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.core.security import create_embedding_probe_token, verify_special_token
from app.db.models.knowledge_base import KnowledgeBase
from app.services.embedding_resolution import TargetIdentity

PROBE_TOKEN_TTL = timedelta(minutes=10)
"""How long after a passing test the save may still be made."""

_TOKEN_TYPE = "embedding_probe"


class ProbePurpose(StrEnum):
    """Which save a test was for; the token's audience."""

    KB_CREATE = "kb_create"
    KB_CHANGE = "kb_change"
    CONNECTION_CHANGE = "connection_change"


@dataclass(frozen=True)
class ProbeBinding:
    """Everything whose change could move a collection's vector space."""

    purpose: ProbePurpose
    provider: str
    connection_id: UUID | None
    base_url: str
    secret_id: UUID | None
    key_generation: UUID | None
    model: str | None
    dim: int | None
    knowledge_bases: tuple[tuple[UUID, str, int], ...]
    """The knowledge bases tested, as `(id, model, dim)`, sorted."""

    def fingerprint(self) -> str:
        """A SHA-256 of the canonical form of every bound value, as hex."""
        canonical = {
            "purpose": self.purpose.value,
            "provider": self.provider,
            "connection_id": _text(self.connection_id),
            "base_url": self.base_url,
            "secret_id": _text(self.secret_id),
            "key_generation": _text(self.key_generation),
            "model": self.model,
            "dim": self.dim,
            "knowledge_bases": [
                [str(kb_id), model, dim] for kb_id, model, dim in self.knowledge_bases
            ],
        }
        return hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @classmethod
    def of(
        cls,
        purpose: ProbePurpose,
        identity: TargetIdentity,
        *,
        model: str | None,
        dim: int | None,
        knowledge_bases: Iterable[KnowledgeBase],
    ) -> ProbeBinding:
        return cls(
            purpose=purpose,
            provider=identity.provider,
            connection_id=identity.connection_id,
            base_url=identity.base_url,
            secret_id=identity.secret_id,
            key_generation=identity.key_generation,
            model=model,
            dim=dim,
            knowledge_bases=tuple(
                sorted(
                    ((kb.id, kb.embedding_model, kb.embedding_dim) for kb in knowledge_bases),
                    key=lambda entry: (str(entry[0]), entry[1], entry[2]),
                )
            ),
        )


@dataclass(frozen=True)
class ProbeClaims:
    """What a verified token says: the fingerprint it was minted for and the width."""

    fingerprint: str
    dim: int | None

    def require_match(self, binding: ProbeBinding) -> None:
        """Refuse a save whose settings are not the ones that were tested.

        Raises:
            BadRequestError: On `probe_token`.
        """
        if not hmac.compare_digest(self.fingerprint, binding.fingerprint()):
            raise refused_field(
                "probe_token", "These settings changed since they were tested - test again."
            )


def mint_probe_token(ctx: AuthContext, binding: ProbeBinding) -> tuple[str, datetime]:
    """Sign a proof for `binding`, and say when it stops being good."""
    token = create_embedding_probe_token(
        subject=ctx.subject_id,
        organization_id=ctx.organization_id,
        purpose=binding.purpose.value,
        fingerprint=binding.fingerprint(),
        dim=binding.dim,
        expires_in=PROBE_TOKEN_TTL,
    )
    return token, datetime.now(UTC) + PROBE_TOKEN_TTL


def read_probe_token(token: str | None, *, ctx: AuthContext, purpose: ProbePurpose) -> ProbeClaims:
    """Verify a proof for this caller and this save, or refuse the save.

    Raises:
        BadRequestError: On `probe_token`, when there is none, when it is not a
            valid, unexpired one for this purpose, or when it was minted for
            another person or organization.
    """
    if token is None:
        raise refused_field(
            "probe_token", "Test these settings before saving, or save them without a test."
        )
    payload = verify_special_token(token, _TOKEN_TYPE, audience=(purpose.value,))
    if (
        payload is None
        or payload.get("sub") != str(ctx.subject_id)
        or payload.get("org") != _text(ctx.organization_id)
    ):
        raise refused_field(
            "probe_token", "This test has expired or belongs to someone else - test again."
        )
    dim = payload.get("dim")
    return ProbeClaims(fingerprint=str(payload["fp"]), dim=None if dim is None else int(dim))


def _text(value: UUID | None) -> str | None:
    """How an id is written in a token and in the fingerprint; the same on both sides."""
    return None if value is None else str(value)
