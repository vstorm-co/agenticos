"""Which embedding model - and whose credential - a collection embeds with.

The vector store used to read one model and one key for the whole deployment:
`EMBEDDING_MODEL` decided every collection's vector width and
`OPENROUTER_API_KEY` paid for every embedding. Collections already *record*
their model and dimension at creation; this module is what makes the record
operative. The store asks per collection, and the answer carries the model the
collection was built with, the width its table was created at, and the key the
organization chose - falling back to the deployment's when it chose none.

The fallback is deliberate, not transitional. A collection with no
`embedding_secret_id` embeds on the deployment key exactly as before, so
nothing breaks the day this lands; an organization that wants its own billing
picks a vault key at creation. A *missing or unopenable* chosen key also falls
back - with a log line - because "the org deleted a secret" must degrade to
the deployment's key, not take document search down.

What the fallback must not do is stay quiet about itself. Three of the five
:class:`EmbeddingKeySource` values are a collection asking for its
organization's key and not getting it, and a `logger.warning` in this module
reaches neither the flow log a worker's operator reads nor the error the
upload leaves on the document row. So the source travels *with* the
resolution, and both surfaces name it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.knowledge_base import KnowledgeBase
from app.db.session import get_db_context
from app.repositories import knowledge_base_repo, organization_secret_repo

logger = logging.getLogger(__name__)

# Secret purposes that can pay for embeddings. OpenRouter is the embeddings
# route today; the tuple exists so a second provider is one entry, not a hunt.
EMBEDDING_KEY_PURPOSES = ("openrouter",)


class EmbeddingKeySource(StrEnum):
    """Which credential a collection's embeddings actually went out on.

    Four of these five mean the deployment key paid, and only one of those
    four is the collection never having chosen otherwise. Telling them apart
    is the difference between "configure a key" and "the key you configured is
    gone", which is the whole of what an operator needs from the message.
    """

    ORGANIZATION = "organization"
    DEPLOYMENT = "deployment"
    SECRET_MISSING = "secret_missing"
    SECRET_UNUSABLE = "secret_unusable"
    SECRET_WRONG_KIND = "secret_wrong_kind"

    @property
    def explanation(self) -> str:
        """The clause a log line or an error message says out loud."""
        return _EXPLANATIONS[self]

    @property
    def is_degraded(self) -> bool:
        """True when the collection asked for a key and did not get it.

        `DEPLOYMENT` is not degraded: a collection that chose no key is
        supposed to embed on the deployment's, and saying so on every document
        would bury the three that matter.
        """
        return self in _DEGRADED


_EXPLANATIONS = {
    EmbeddingKeySource.ORGANIZATION: "the vault key the collection chose",
    EmbeddingKeySource.DEPLOYMENT: (
        "the deployment's OPENROUTER_API_KEY, because the collection chose no key of its own"
    ),
    EmbeddingKeySource.SECRET_MISSING: (
        "the deployment's OPENROUTER_API_KEY, because the vault key the collection chose "
        "is no longer in this organization's vault"
    ),
    EmbeddingKeySource.SECRET_UNUSABLE: (
        "the deployment's OPENROUTER_API_KEY, because the vault key the collection chose "
        "could not be unsealed"
    ),
    EmbeddingKeySource.SECRET_WRONG_KIND: (
        "the deployment's OPENROUTER_API_KEY, because the vault entry the collection chose "
        "does not hold an API key"
    ),
}

_DEGRADED = frozenset(
    {
        EmbeddingKeySource.SECRET_MISSING,
        EmbeddingKeySource.SECRET_UNUSABLE,
        EmbeddingKeySource.SECRET_WRONG_KIND,
    }
)


@dataclass(frozen=True, repr=False)
class ResolvedEmbeddings:
    """Everything one collection's embedding call needs.

    `repr=False` on purpose: the dataclass carries a plaintext key, and the
    default repr is the way a key ends up in a log line.
    """

    model: str
    dim: int
    api_key: str
    key_source: EmbeddingKeySource

    def __repr__(self) -> str:
        return (
            f"ResolvedEmbeddings(model={self.model!r}, dim={self.dim}, "
            f"api_key='***', key_source={self.key_source.value!r})"
        )

    def describe(self, collection_name: str) -> str:
        """One sentence-fragment naming the collection and the key it embeds on.

        Written once here rather than at each surface so the flow log and the
        failure on the document row cannot drift apart.
        """
        return f"collection {collection_name!r}, which embeds on {self.key_source.explanation}"


async def embeddings_for_collection(
    collection_name: str, organization_id: UUID | None
) -> ResolvedEmbeddings | None:
    """Resolve one collection's embedding model and credential, for one organization.

    Returns None for a collection no knowledge base claims - the store then
    uses its deployment defaults, which is what such collections have always
    gotten. Opens its own session because the store embeds from places with no
    request in sight: a worker mid-ingestion, a capability mid-run.

    `organization_id` is required and scopes the resolution: `collection_name`
    is not unique across tenants, so resolving by name alone could return - and
    unseal and bill - another organization's key (#913). The caller passes the
    organization the search or ingest is acting for; `None` only where there is
    no tenant (a CLI ingest).
    """
    async with get_db_context() as db:
        kb = await knowledge_base_repo.get_for_collection(db, collection_name, organization_id)
        if kb is None:
            return None
        api_key, key_source = await _api_key_for(db, kb)
        return ResolvedEmbeddings(
            model=kb.embedding_model,
            # The recorded width, not a fresh lookup: the table was created at
            # this number, and a later catalog change must not disagree with it.
            dim=kb.embedding_dim,
            api_key=api_key,
            key_source=key_source,
        )


async def _api_key_for(db: AsyncSession, kb: KnowledgeBase) -> tuple[str, EmbeddingKeySource]:
    """The organization's chosen key, or the deployment's, and which of the two.

    Every failure path lands on the deployment key with a log line rather than
    an exception: the choice of *whose key pays* must never decide *whether
    documents can be found*. The second element is what stops that policy from
    being invisible - it is carried out to the flow log and the error message.
    """
    if kb.embedding_secret_id is None or kb.organization_id is None:
        return settings.OPENROUTER_API_KEY, EmbeddingKeySource.DEPLOYMENT

    row = await organization_secret_repo.get(
        db, kb.embedding_secret_id, organization_id=kb.organization_id
    )
    if row is None:
        logger.warning("embedding_secret_missing", extra={"collection": kb.collection_name})
        return settings.OPENROUTER_API_KEY, EmbeddingKeySource.SECRET_MISSING
    try:
        secret = unseal_secret(
            row.sealed_secret,
            kind=SecretKind(row.kind),
            scope=VaultScope.organization(kb.organization_id),
            key_version=row.key_version,
        )
    except Exception:
        logger.warning("embedding_secret_unusable", extra={"collection": kb.collection_name})
        return settings.OPENROUTER_API_KEY, EmbeddingKeySource.SECRET_UNUSABLE
    if not isinstance(secret, ApiKeySecret):
        logger.warning("embedding_secret_wrong_kind", extra={"collection": kb.collection_name})
        return settings.OPENROUTER_API_KEY, EmbeddingKeySource.SECRET_WRONG_KIND
    return secret.api_key.get_secret_value(), EmbeddingKeySource.ORGANIZATION
