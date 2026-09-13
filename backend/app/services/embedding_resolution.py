"""Which embedding model - and whose credential - a collection embeds with.

The vector store used to read one model and one key for the whole deployment:
`EMBEDDING_MODEL` decided every collection's vector width and a single
`OPENROUTER_API_KEY` paid for every embedding. Collections already *record*
their model, their provider and their key at creation; this module is what
makes the record operative. The store asks per collection, and the answer
carries the model the collection was built with, the width its table was
created at, the provider's address and the vault key the organization chose.

**There is no deployment-wide key to fall back to.** A collection names the
organization vault key that pays for its embeddings, the way an agent names the
model profile that pays for its chat - and a collection that names none, or
whose key has since been deleted, unsealed wrongly or turned out not to be an
API key, resolves to *no* key. The embedding client turns that into a refusal
naming the collection and the reason, at the moment somebody tries to index or
search it; nothing is refused at resolution, because *whose key pays* must
never decide *whether the row can be read*.

What the resolution must not do is stay quiet about itself. Four of the five
:class:`EmbeddingKeySource` values are a collection asking for a key and not
getting it, and a `logger.warning` in this module reaches neither the flow log
a worker's operator reads nor the error the upload leaves on the document row.
So the source travels *with* the resolution, and both surfaces name it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.knowledge_base import KnowledgeBase
from app.db.session import get_db_context
from app.repositories import knowledge_base_repo, organization_secret_repo
from app.services.rag import embedding_providers

logger = logging.getLogger(__name__)


class EmbeddingKeySource(StrEnum):
    """Which credential a collection's embeddings actually went out on.

    One means a key was found - the collection's own. The other four mean no
    key was, and telling them apart is the difference between "choose a key",
    "the key you chose is gone", "the key you chose cannot be opened" and "the
    vault entry you chose is not an API key", which is the whole of what an
    operator needs from the message.
    """

    ORGANIZATION = "organization"
    NONE_CHOSEN = "none_chosen"
    SECRET_MISSING = "secret_missing"
    SECRET_UNUSABLE = "secret_unusable"
    SECRET_WRONG_KIND = "secret_wrong_kind"

    @property
    def explanation(self) -> str:
        """The clause a log line or an error message says out loud."""
        return _EXPLANATIONS[self]

    @property
    def is_degraded(self) -> bool:
        """True when the collection did not get a key to embed on."""
        return self is not EmbeddingKeySource.ORGANIZATION


_EXPLANATIONS = {
    EmbeddingKeySource.ORGANIZATION: "the vault key the collection chose",
    EmbeddingKeySource.NONE_CHOSEN: (
        "no key at all, because the collection names no vault key - choose one for its "
        "provider from the organization's vault"
    ),
    EmbeddingKeySource.SECRET_MISSING: (
        "no key at all, because the vault key the collection chose is no longer in this "
        "organization's vault"
    ),
    EmbeddingKeySource.SECRET_UNUSABLE: (
        "no key at all, because the vault key the collection chose could not be unsealed"
    ),
    EmbeddingKeySource.SECRET_WRONG_KIND: (
        "no key at all, because the vault entry the collection chose does not hold an API key"
    ),
}


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
    # Where the request goes, from the collection's provider. Carried with the
    # key rather than read from a constant, because the two have to agree: an
    # address without its credential is how a key reaches the wrong vendor.
    base_url: str
    provider: str

    def __repr__(self) -> str:
        return (
            f"ResolvedEmbeddings(model={self.model!r}, dim={self.dim}, "
            f"api_key='***', key_source={self.key_source.value!r}, "
            f"provider={self.provider!r})"
        )

    def describe(self, collection_name: str) -> str:
        """One sentence-fragment naming the collection and the key it embeds on.

        Written once here rather than at each surface so the flow log and the
        failure on the document row cannot drift apart.
        """
        return (
            f"collection {collection_name!r}, which embeds through {self.provider} "
            f"on {self.key_source.explanation}"
        )


async def embeddings_for_collection(
    collection_name: str, organization_id: UUID | None = None
) -> ResolvedEmbeddings | None:
    """Resolve one collection's embedding model, provider and credential.

    Returns None for a collection no knowledge base claims - the store then
    uses its own embedder, which has no key and refuses on first use, because
    such a collection has nothing to pay with. Opens its own session because
    the store embeds from places with no request in sight: a worker
    mid-ingestion, a capability mid-run.

    `organization_id` scopes the resolution: `collection_name` is not unique, so
    resolving by name alone can land on another tenant's knowledge base and unseal
    *their* vault key for *this* organization's embedding call (#913). The caller
    passes the organization it is embedding for - the ingesting flow's, the
    searching agent's - and resolution stays within it, falling back to an
    app-scoped collection but never to a third organization's. `None` is a caller
    with no organization in hand and keeps the first-match behaviour it had.

    A provider the catalog no longer names - an entry removed from the file
    under a collection that was using it - resolves to the first entry the
    catalog still holds, with a log line and **without its key**: the key was
    stored for the provider that is gone, and sending it to whichever address
    is left would hand one vendor's credential to another. The collection
    refuses to embed until somebody moves it to a provider that exists and
    gives it a key for that one.
    """
    async with get_db_context() as db:
        kb = await knowledge_base_repo.get_for_collection(db, collection_name, organization_id)
        if kb is None:
            return None
        provider = embedding_providers.get(kb.embedding_provider)
        if provider is None:
            logger.warning(
                "embedding_provider_unknown",
                extra={"collection": collection_name, "provider": kb.embedding_provider},
            )
            provider = embedding_providers.providers()[0]
            api_key, key_source = "", EmbeddingKeySource.NONE_CHOSEN
        else:
            api_key, key_source = await _api_key_for(db, kb)
        return ResolvedEmbeddings(
            model=kb.embedding_model,
            # The recorded width, not a fresh lookup: the table was created at
            # this number, and a later catalog change must not disagree with it.
            dim=kb.embedding_dim,
            api_key=api_key,
            key_source=key_source,
            base_url=provider.base_url,
            provider=provider.provider,
        )


async def _api_key_for(db: AsyncSession, kb: KnowledgeBase) -> tuple[str, EmbeddingKeySource]:
    """The organization's chosen key, or none - and which.

    A failure to open the collection's own key degrades to no key rather than
    raising: the choice of *whose key pays* must never decide *whether the
    collection's row can be read*. The second element is what stops that from
    being invisible: it is carried out to the flow log and to the error on the
    document row.
    """
    if kb.embedding_secret_id is None or kb.organization_id is None:
        return "", EmbeddingKeySource.NONE_CHOSEN

    row = await organization_secret_repo.get(
        db, kb.embedding_secret_id, organization_id=kb.organization_id
    )
    if row is None:
        logger.warning("embedding_secret_missing", extra={"collection": kb.collection_name})
        return "", EmbeddingKeySource.SECRET_MISSING
    try:
        secret = unseal_secret(
            row.sealed_secret,
            kind=SecretKind(row.kind),
            scope=VaultScope.organization(kb.organization_id),
            key_version=row.key_version,
        )
    except Exception:
        logger.warning("embedding_secret_unusable", extra={"collection": kb.collection_name})
        return "", EmbeddingKeySource.SECRET_UNUSABLE
    if not isinstance(secret, ApiKeySecret):
        logger.warning("embedding_secret_wrong_kind", extra={"collection": kb.collection_name})
        return "", EmbeddingKeySource.SECRET_WRONG_KIND
    return secret.api_key.get_secret_value(), EmbeddingKeySource.ORGANIZATION
