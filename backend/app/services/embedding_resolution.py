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
model profile that pays for its chat - and a collection that names none, that
has no organization vault to name one from, whose key has since been unsealed
wrongly or turned out not to be an API key, or whose recorded provider this
build no longer offers, resolves to *no* key. The embedding client turns that
into a refusal naming the collection and the reason, at the moment somebody
tries to index or search it; nothing is refused at resolution, because *whose
key pays* must never decide *whether the row can be read*.

The one provider that wants no key is `ollama`, a server on the deployment's own
network (#1632). The catalog holds no address for it; the collection names a
local service (`local_services`) that does, and resolves to `KEYLESS` with that
address - not a degradation, and how an app-scoped collection, which has no
vault, embeds at all (#1631).

What the resolution must not do is stay quiet about itself. Every
:class:`EmbeddingKeySource` value but two is a collection asking for a key and
not getting it, and a `logger.warning` in this module reaches neither the flow
log a worker's operator reads nor the error the upload leaves on the document
row. So the source travels *with* the resolution, and both surfaces name it.
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
from app.repositories import knowledge_base_repo, local_service_repo, organization_secret_repo
from app.services.rag import embedding_providers

logger = logging.getLogger(__name__)


class EmbeddingKeySource(StrEnum):
    """Which credential a collection's embeddings actually went out on.

    Two mean the request can go out - on the collection's own key, or on none
    because the provider is a keyless endpoint on the deployment's own network.
    The others mean a key was needed and not found, and telling them apart is
    the difference between "choose a key", "this collection has no vault to
    choose one from", "the key you chose is gone", "the key you chose cannot be
    opened", "the vault entry you chose is not an API key" and "the provider
    this collection recorded no longer exists", which is the whole of what an
    operator needs from the message - each names a different remedy.

    `NO_VAULT` is an app-scoped collection on a keyed provider: it belongs to no
    organization, so there is no vault it could name a key from, and there is
    no deployment-wide key either - it can embed only through a keyless
    provider (#1631). `PROVIDER_UNKNOWN` is a catalog entry removed from
    `embedding_providers.json` under a collection that was using it; the key it
    holds was stored for the provider that is gone, so it stays sealed.
    `ENDPOINT_MISSING` and `ENDPOINT_PAUSED` are a keyless collection whose local
    service was deleted (the column is `SET NULL`) or turned off - the two
    remedies differ, so the two are told apart.
    """

    ORGANIZATION = "organization"
    KEYLESS = "keyless"
    NONE_CHOSEN = "none_chosen"
    NO_VAULT = "no_vault"
    SECRET_MISSING = "secret_missing"
    SECRET_UNUSABLE = "secret_unusable"
    SECRET_WRONG_KIND = "secret_wrong_kind"
    PROVIDER_UNKNOWN = "provider_unknown"
    ENDPOINT_MISSING = "endpoint_missing"
    ENDPOINT_PAUSED = "endpoint_paused"

    @property
    def explanation(self) -> str:
        """The clause a log line or an error message says out loud."""
        return _EXPLANATIONS[self]

    @property
    def is_degraded(self) -> bool:
        """True when the collection needed a key and did not get one."""
        return self not in _CAN_EMBED


_CAN_EMBED = frozenset({EmbeddingKeySource.ORGANIZATION, EmbeddingKeySource.KEYLESS})

_EXPLANATIONS = {
    EmbeddingKeySource.ORGANIZATION: "the vault key the collection chose",
    EmbeddingKeySource.KEYLESS: (
        "no key, at the local service the collection names on the deployment's own network"
    ),
    EmbeddingKeySource.NONE_CHOSEN: (
        "no key at all, because the collection names no vault key - choose one for its "
        "provider from the organization's vault"
    ),
    EmbeddingKeySource.NO_VAULT: (
        "no key at all, because an app-scoped collection belongs to no organization and so "
        "has no vault to hold one - move it to a keyless provider on the deployment's own "
        "network, the one way such a collection can embed (#1631)"
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
    EmbeddingKeySource.PROVIDER_UNKNOWN: (
        "no key at all, because that provider is no longer in this build's catalog - move the "
        "collection to one that is, and give it a key for that one"
    ),
    EmbeddingKeySource.ENDPOINT_MISSING: (
        "no address, because the local service the collection named is gone - choose another "
        "under Knowledge, or register one"
    ),
    EmbeddingKeySource.ENDPOINT_PAUSED: (
        "no address, because the local service the collection names is turned off - turn it "
        "on under Knowledge, or choose another"
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
    # Empty, with an empty key, for a provider this build no longer offers.
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
    under a collection that was using it - resolves to the provider the row
    recorded, **no address and no key**: the key was stored for the provider
    that is gone, and sending it to whichever address is left would hand one
    vendor's credential to another. The row can still be read (its model and
    width are its own), and the refusal on the first index or search says the
    provider is the problem, which the earlier `logger.warning` alone did not.
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
            api_key, key_source, base_url = "", EmbeddingKeySource.PROVIDER_UNKNOWN, ""
        elif provider.keyless:
            # Whatever key the row may still hold from a keyed provider it left
            # is not opened: this endpoint takes none, and unsealing a credential
            # nothing will send is a read of the vault for no reason.
            api_key = ""
            base_url, key_source = await _endpoint_for(db, kb)
        else:
            api_key, key_source = await _api_key_for(db, kb)
            base_url = provider.base_url or ""
        return ResolvedEmbeddings(
            model=kb.embedding_model,
            # The recorded width, not a fresh lookup: the table was created at
            # this number, and a later catalog change must not disagree with it.
            dim=kb.embedding_dim,
            api_key=api_key,
            key_source=key_source,
            base_url=base_url,
            provider=kb.embedding_provider,
        )


async def _endpoint_for(db: AsyncSession, kb: KnowledgeBase) -> tuple[str, EmbeddingKeySource]:
    """Where a keyless collection's provider answers, or nowhere - and which.

    The row is read within what the collection may name - its organization's
    services and the deployment's - so a service id that leaked from another
    tenant resolves to nothing rather than to their host. Degrades like the key
    lookup: the address travels with the reason, and the client refuses.
    """
    if kb.embedding_endpoint_id is None:
        return "", EmbeddingKeySource.ENDPOINT_MISSING
    row = await local_service_repo.get_visible(
        db, kb.embedding_endpoint_id, organization_id=kb.organization_id
    )
    if row is None:
        logger.warning("embedding_endpoint_missing", extra={"collection": kb.collection_name})
        return "", EmbeddingKeySource.ENDPOINT_MISSING
    if not row.is_active:
        return "", EmbeddingKeySource.ENDPOINT_PAUSED
    return row.base_url, EmbeddingKeySource.KEYLESS


async def _api_key_for(db: AsyncSession, kb: KnowledgeBase) -> tuple[str, EmbeddingKeySource]:
    """The organization's chosen key, or none - and which.

    A failure to open the collection's own key degrades to no key rather than
    raising: the choice of *whose key pays* must never decide *whether the
    collection's row can be read*. The second element is what stops that from
    being invisible: it is carried out to the flow log and to the error on the
    document row.
    """
    if kb.organization_id is None:
        return "", EmbeddingKeySource.NO_VAULT
    if kb.embedding_secret_id is None:
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
