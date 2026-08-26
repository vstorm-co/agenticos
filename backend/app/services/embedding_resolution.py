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

**The fallback stops at the provider the deployment's key belongs to.** A
collection embedding through OpenAI cannot be paid for with the deployment's
OpenRouter key: that request is refused by the provider, and on the way to
being refused it puts one vendor's credential in another vendor's logs. So a
collection on another provider with no usable key of its own resolves to *no*
key, which the embedding client turns into a refusal naming what it tried -
the same shape as a deployment that never configured one.

What the fallback must not do is stay quiet about itself. Four of the six
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

from app.core.config import settings
from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.knowledge_base import KnowledgeBase
from app.db.session import get_db_context
from app.repositories import knowledge_base_repo, organization_secret_repo
from app.services.rag import embedding_providers

logger = logging.getLogger(__name__)


class EmbeddingKeySource(StrEnum):
    """Which credential a collection's embeddings actually went out on.

    Two mean a key was found - the collection's own, or the deployment's, which
    the collection is entitled to only while it embeds through the provider that
    key belongs to. The other four mean no key was, and telling them apart is
    the difference between "configure a key", "the key you configured is gone"
    and "the key this deployment has is for somebody else's endpoint", which is
    the whole of what an operator needs from the message.
    """

    ORGANIZATION = "organization"
    DEPLOYMENT = "deployment"
    SECRET_MISSING = "secret_missing"
    SECRET_UNUSABLE = "secret_unusable"
    SECRET_WRONG_KIND = "secret_wrong_kind"
    FOREIGN_PROVIDER = "foreign_provider"

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
        "no key at all, because the vault key the collection chose is no longer in this "
        "organization's vault"
    ),
    EmbeddingKeySource.SECRET_UNUSABLE: (
        "no key at all, because the vault key the collection chose could not be unsealed"
    ),
    EmbeddingKeySource.SECRET_WRONG_KIND: (
        "no key at all, because the vault entry the collection chose does not hold an API key"
    ),
    EmbeddingKeySource.FOREIGN_PROVIDER: (
        "no key at all, because the deployment's key belongs to another provider and sending "
        "it here would hand one vendor's credential to another"
    ),
}

_DEGRADED = frozenset(
    {
        EmbeddingKeySource.SECRET_MISSING,
        EmbeddingKeySource.SECRET_UNUSABLE,
        EmbeddingKeySource.SECRET_WRONG_KIND,
        EmbeddingKeySource.FOREIGN_PROVIDER,
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
    collection_name: str, organization_id: UUID | None, knowledge_base_id: UUID | None = None
) -> ResolvedEmbeddings | None:
    """Resolve one collection's embedding model, provider and credential.

    Returns None for a collection no knowledge base claims - the store then
    uses its deployment defaults, which is what such collections have always
    gotten. Opens its own session because the store embeds from places with no
    request in sight: a worker mid-ingestion, a capability mid-run.

    `knowledge_base_id`, when given, is the knowledge base the caller was already
    authorized against, and resolution reads *that* row. `collection_name` is not
    unique, so a name+organization lookup can return a different row than the
    access check authorized - a restricted `org` collection sharing an `app`
    collection's name - and then unseal and bill a key the caller was never
    granted (#913). The search path passes the authorized id; ingestion and the
    CLI, which choose the row themselves, pass none and fall back to the
    `organization_id`-scoped lookup.

    A provider the catalog no longer names - an entry removed from the file
    under a collection that was using it - resolves to the deployment's, with a
    log line. The alternative is a collection nobody can search because a
    catalog edit took its address away, and the deployment's provider is the one
    address this build is certain of.
    """
    async with get_db_context() as db:
        kb = (
            await knowledge_base_repo.get_by_id(db, knowledge_base_id)
            if knowledge_base_id is not None
            else await knowledge_base_repo.get_for_collection(db, collection_name, organization_id)
        )
        if kb is None:
            return None
        provider = embedding_providers.get(kb.embedding_provider)
        if provider is None:
            logger.warning(
                "embedding_provider_unknown",
                extra={"collection": collection_name, "provider": kb.embedding_provider},
            )
            provider = embedding_providers.deployment_provider()
        api_key, key_source = await _api_key_for(db, kb, provider)
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


async def _api_key_for(
    db: AsyncSession,
    kb: KnowledgeBase,
    provider: embedding_providers.EmbeddingProviderEntry,
) -> tuple[str, EmbeddingKeySource]:
    """The organization's chosen key, the deployment's, or none - and which.

    A failure to open the collection's own key degrades rather than raising: the
    choice of *whose key pays* must never decide *whether documents can be
    found*. What it degrades to depends on the provider, because the deployment
    has exactly one key and it belongs to exactly one endpoint - so a collection
    on another provider degrades to no key rather than to somebody else's.

    The second element is what stops either policy from being invisible: it is
    carried out to the flow log and to the error on the document row.
    """
    deployment_key = settings.OPENROUTER_API_KEY if provider.deployment_key else ""
    fallback = (
        EmbeddingKeySource.DEPLOYMENT
        if provider.deployment_key
        else EmbeddingKeySource.FOREIGN_PROVIDER
    )
    if kb.embedding_secret_id is None or kb.organization_id is None:
        return deployment_key, fallback

    row = await organization_secret_repo.get(
        db, kb.embedding_secret_id, organization_id=kb.organization_id
    )
    if row is None:
        logger.warning("embedding_secret_missing", extra={"collection": kb.collection_name})
        return deployment_key, _degraded(EmbeddingKeySource.SECRET_MISSING, fallback)
    try:
        secret = unseal_secret(
            row.sealed_secret,
            kind=SecretKind(row.kind),
            scope=VaultScope.organization(kb.organization_id),
            key_version=row.key_version,
        )
    except Exception:
        logger.warning("embedding_secret_unusable", extra={"collection": kb.collection_name})
        return deployment_key, _degraded(EmbeddingKeySource.SECRET_UNUSABLE, fallback)
    if not isinstance(secret, ApiKeySecret):
        logger.warning("embedding_secret_wrong_kind", extra={"collection": kb.collection_name})
        return deployment_key, _degraded(EmbeddingKeySource.SECRET_WRONG_KIND, fallback)
    return secret.api_key.get_secret_value(), EmbeddingKeySource.ORGANIZATION


def _degraded(reason: EmbeddingKeySource, fallback: EmbeddingKeySource) -> EmbeddingKeySource:
    """Why the collection's own key was not used, or that there is nothing to use.

    `FOREIGN_PROVIDER` wins over the three reasons a chosen key failed: with no
    key to fall back to, "the vault entry is gone" is the second thing an
    operator needs to know and "there is no key for this provider" is the first.
    """
    return reason if fallback is EmbeddingKeySource.DEPLOYMENT else fallback
