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

Two providers are reached through a service connection (`service_connections`)
instead of the catalog's address. `ollama` is a server on the deployment's own
network (#1632) and wants no key; the collection names the connection that holds
its address and resolves to `KEYLESS` - not a degradation, and how an app-scoped
collection, which has no vault, embeds at all (#1631). `openai_compatible` is any
endpoint that speaks the same route: the connection holds its address and, when the
endpoint wants one, the organization's vault key, which resolves to `CONNECTION`.

Resolution is two steps so that a caller who must not hold a plaintext key can
still say *what* a collection would embed through. `identify_target` reads the rows
and names the target without opening any key; `open_target` unseals it.

What the resolution must not do is stay quiet about itself. Every
:class:`EmbeddingKeySource` value but two is a collection asking for a key and
not getting it, and a `logger.warning` in this module reaches neither the flow
log a worker's operator reads nor the error the upload leaves on the document
row. So the source travels *with* the resolution, and both surfaces name it.
"""

import logging
from dataclasses import dataclass, field, replace
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.service_connection import ServiceConnection
from app.db.session import get_db_context
from app.db.vector_tables import VectorScope
from app.repositories import knowledge_base_repo, organization_secret_repo, service_connection_repo
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
    `ENDPOINT_MISSING` and `ENDPOINT_PAUSED` are a collection whose service
    connection was deleted (the column is `SET NULL`) or turned off - the two
    remedies differ, so the two are told apart.

    `CONNECTION` is a custom endpoint answering with the key its connection
    carries. `CONNECTION_KEY_MISSING` is a connection that needs a key and has
    none - it was never given one, or the vault entry was deleted (`secret_id` is
    `SET NULL`, `requires_key` stays) - and `CONNECTION_KEY_UNUSABLE` one whose key
    could not be opened or is not an API key. A keyed endpoint is never called bare.
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
    CONNECTION = "connection"
    CONNECTION_KEY_MISSING = "connection_key_missing"
    CONNECTION_KEY_UNUSABLE = "connection_key_unusable"

    @property
    def explanation(self) -> str:
        """The clause a log line or an error message says out loud."""
        return _EXPLANATIONS[self]

    @property
    def is_degraded(self) -> bool:
        """True when the collection needed a key and did not get one."""
        return self not in _CAN_EMBED


_CAN_EMBED = frozenset(
    {EmbeddingKeySource.ORGANIZATION, EmbeddingKeySource.KEYLESS, EmbeddingKeySource.CONNECTION}
)

_EXPLANATIONS = {
    EmbeddingKeySource.ORGANIZATION: "the vault key the collection chose",
    EmbeddingKeySource.KEYLESS: "no key, at the service connection the collection names",
    EmbeddingKeySource.CONNECTION: ("the vault key of the service connection the collection names"),
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
        "no address, because the service connection the collection named is gone - choose another "
        "under Knowledge, or register one"
    ),
    EmbeddingKeySource.ENDPOINT_PAUSED: (
        "no address, because the service connection the collection names is turned off - turn it "
        "on under Knowledge, or choose another"
    ),
    EmbeddingKeySource.CONNECTION_KEY_MISSING: (
        "no address, because the service connection the collection names needs a vault key "
        "and has none - give it one under Knowledge"
    ),
    EmbeddingKeySource.CONNECTION_KEY_UNUSABLE: (
        "no address, because the vault key of the service connection the collection names "
        "could not be opened or does not hold an API key - give it another under Knowledge"
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
    # The chunks of the shared runtime table this collection's base holds: its
    # tenant (#1684) and the base itself (#2537). A collection name is not
    # unique, so bases of different tenants - and of one tenant - share one
    # physical table; this keeps each base's rows its own. Resolution is already
    # the place that maps a caller's organization to the one knowledge base it may
    # read for a shared name (#913), so the scope rides home with the key rather
    # than being resolved a second time.
    vector_scope: VectorScope

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
        target = await open_target(
            db,
            await identify_target(db, EmbeddingSettings.of(kb), organization_id=kb.organization_id),
            collection=collection_name,
        )
        return ResolvedEmbeddings(
            model=kb.embedding_model,
            # The recorded width, not a fresh lookup: the table was created at
            # this number, and a later catalog change must not disagree with it.
            dim=kb.embedding_dim,
            api_key=target.api_key,
            key_source=target.identity.key_source,
            base_url=target.identity.base_url,
            provider=kb.embedding_provider,
            vector_scope=kb.vector_scope,
        )


def public_address(url: str | None) -> str | None:
    """An address as an audit entry may keep it: scheme, host, port and path.

    A query string can carry a key (`?api-key=...`) and a netloc can carry a
    password; neither is a setting anyone needs to read back.
    """
    if url is None:
        return None
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port is not None else ""
    return f"{parts.scheme}://{host}{port}{parts.path}"


@dataclass(frozen=True)
class EmbeddingSettings:
    """What a collection - or a proposed change to one - says it embeds through."""

    provider: str
    endpoint_id: UUID | None
    secret_id: UUID | None
    base_url: str | None
    model: str
    # Only to name the collection in a log line; it decides nothing.
    collection: str = field(default="", compare=False)

    def for_audit(self) -> dict[str, str | None]:
        """The settings an audit entry records: ids and names, an address without its query, no key."""
        return {
            "provider": self.provider,
            "endpoint_id": None if self.endpoint_id is None else str(self.endpoint_id),
            "secret_id": None if self.secret_id is None else str(self.secret_id),
            "base_url": public_address(self.base_url),
            "model": self.model,
        }

    @classmethod
    def of(cls, kb: KnowledgeBase) -> EmbeddingSettings:
        """What the row embeds through. A base reached through a connection has no key or
        address of its own - the connection holds both - so a leftover on the row is not read."""
        provider = embedding_providers.get(kb.embedding_provider)
        own = provider is None or not provider.via_connection
        return cls(
            provider=kb.embedding_provider,
            endpoint_id=kb.embedding_endpoint_id,
            secret_id=kb.embedding_secret_id if own else None,
            base_url=kb.embedding_base_url if own else None,
            model=kb.embedding_model,
            collection=kb.collection_name,
        )


@dataclass(frozen=True)
class TargetIdentity:
    """Where embeddings would go and on whose credential, with no plaintext.

    What a probe's token is bound to, so every field is something whose change
    could move a collection's vector space: the connection and its address, the
    key by id and by `authorization_generation` (a rotated value is a new
    generation), and the source that says whether the target can embed at all.
    `key_source` here is what the rows say; :func:`open_target` may still find the
    key unusable.
    """

    provider: str
    connection_id: UUID | None
    base_url: str
    secret_id: UUID | None
    key_generation: UUID | None
    key_organization_id: UUID | None
    key_source: EmbeddingKeySource


@dataclass(frozen=True, repr=False)
class EmbeddingTarget:
    """An identity with its key opened. `repr=False`: it carries a plaintext key."""

    identity: TargetIdentity
    api_key: str

    @property
    def keyless(self) -> bool:
        return self.identity.key_source is EmbeddingKeySource.KEYLESS

    def __repr__(self) -> str:
        return f"EmbeddingTarget(identity={self.identity!r}, api_key='***')"


def _unresolved(provider: str, source: EmbeddingKeySource, *, base_url: str = "") -> TargetIdentity:
    """A target that cannot embed: no key, the address it would have had, and the reason."""
    return TargetIdentity(
        provider=provider,
        connection_id=None,
        base_url=base_url,
        secret_id=None,
        key_generation=None,
        key_organization_id=None,
        key_source=source,
    )


async def identify_target(
    db: AsyncSession, settings: EmbeddingSettings, *, organization_id: UUID | None
) -> TargetIdentity:
    """Name what these settings embed through, reading rows and opening no key.

    Args:
        settings: The collection's recorded settings, or a proposed change's.
        organization_id: Whose service connections and vault the collection may
            name; `None` for an app-scoped collection, which sees the deployment's
            connections alone and has no vault.

    A key that is not there - never chosen, deleted, or out of this organization -
    is a `key_source` that says so, not an exception: whose key pays must never
    decide whether the row can be read.
    """
    provider = embedding_providers.get(settings.provider)
    if provider is None:
        logger.warning(
            "embedding_provider_unknown",
            extra={"collection": settings.collection, "provider": settings.provider},
        )
        return _unresolved(settings.provider, EmbeddingKeySource.PROVIDER_UNKNOWN)
    if provider.via_connection:
        # Whatever key the settings may still hold from a keyed provider they
        # left is not looked at: the connection's key, if it has one, is the only
        # credential this provider sends.
        return await _connection_target(db, settings, organization_id=organization_id)
    base_url = settings.base_url or provider.base_url or ""
    if organization_id is None:
        return _unresolved(settings.provider, EmbeddingKeySource.NO_VAULT, base_url=base_url)
    if settings.secret_id is None:
        return _unresolved(settings.provider, EmbeddingKeySource.NONE_CHOSEN, base_url=base_url)
    generation = await organization_secret_repo.authorization_generation(
        db, settings.secret_id, organization_id=organization_id
    )
    if generation is None:
        logger.warning("embedding_secret_missing", extra={"collection": settings.collection})
        return _unresolved(settings.provider, EmbeddingKeySource.SECRET_MISSING, base_url=base_url)
    return TargetIdentity(
        provider=settings.provider,
        connection_id=None,
        base_url=base_url,
        secret_id=settings.secret_id,
        key_generation=generation,
        key_organization_id=organization_id,
        key_source=EmbeddingKeySource.ORGANIZATION,
    )


async def _connection_target(
    db: AsyncSession, settings: EmbeddingSettings, *, organization_id: UUID | None
) -> TargetIdentity:
    """Where a collection reached through a service connection answers, or nowhere.

    The row is read within what the collection may name - its organization's
    connections and the deployment's - so an id that leaked from another tenant
    resolves to nothing rather than to their host. Degrades like the key lookup:
    the address travels with the reason, and the client refuses.
    """
    if settings.endpoint_id is None:
        return _unresolved(settings.provider, EmbeddingKeySource.ENDPOINT_MISSING)
    row = await service_connection_repo.get_visible(
        db, settings.endpoint_id, organization_id=organization_id
    )
    if row is None:
        logger.warning("embedding_endpoint_missing", extra={"collection": settings.collection})
        return _unresolved(settings.provider, EmbeddingKeySource.ENDPOINT_MISSING)
    if not row.is_active:
        return _unresolved(settings.provider, EmbeddingKeySource.ENDPOINT_PAUSED)
    return await identify_connection(
        db,
        row,
        provider=settings.provider,
        base_url=row.base_url,
        secret_id=row.secret_id,
        requires_key=row.requires_key,
        collection=settings.collection,
    )


async def identify_connection(
    db: AsyncSession,
    row: ServiceConnection,
    *,
    provider: str,
    base_url: str,
    secret_id: UUID | None,
    requires_key: bool,
    collection: str = "",
) -> TargetIdentity:
    """What embeddings through `row` would reach, with `base_url` and `secret_id` as given.

    The row's own values for a stored connection; a proposed edit's for a test of
    one - which is why the address and the key are arguments and not read from
    `row`. Only the row's owner and id are taken from it. A keyed connection whose
    key is not in its owner's vault resolves to the reason, never to a bare call.
    """
    if not requires_key:
        return TargetIdentity(
            provider=provider,
            connection_id=row.id,
            base_url=base_url,
            secret_id=None,
            key_generation=None,
            key_organization_id=None,
            key_source=EmbeddingKeySource.KEYLESS,
        )
    generation = (
        None
        if secret_id is None or row.organization_id is None
        else await organization_secret_repo.authorization_generation(
            db, secret_id, organization_id=row.organization_id
        )
    )
    if generation is None:
        logger.warning("embedding_connection_key_missing", extra={"collection": collection})
        return _unresolved(provider, EmbeddingKeySource.CONNECTION_KEY_MISSING)
    return TargetIdentity(
        provider=provider,
        connection_id=row.id,
        base_url=base_url,
        secret_id=secret_id,
        key_generation=generation,
        key_organization_id=row.organization_id,
        key_source=EmbeddingKeySource.CONNECTION,
    )


async def open_target(
    db: AsyncSession, identity: TargetIdentity, *, collection: str = ""
) -> EmbeddingTarget:
    """Unseal the key an identity names, or degrade it to the reason it cannot.

    A failure to open the key degrades to no key rather than raising, for the
    reason :func:`identify_target` gives. The reason it degrades to is what stops
    that from being invisible: it is carried out to the flow log and to the error
    on the document row.
    """
    if identity.key_source not in _KEYED:
        return EmbeddingTarget(identity=identity, api_key="")
    missing, unusable = _KEY_FAILURES[identity.key_source]
    if identity.secret_id is None or identity.key_organization_id is None:
        return _degraded(identity, missing)
    row = await organization_secret_repo.get(
        db, identity.secret_id, organization_id=identity.key_organization_id
    )
    if row is None:
        logger.warning("embedding_secret_missing", extra={"collection": collection})
        return _degraded(identity, missing)
    try:
        secret = unseal_secret(
            row.sealed_secret,
            kind=SecretKind(row.kind),
            scope=VaultScope.organization(identity.key_organization_id),
            key_version=row.key_version,
        )
    except Exception:
        logger.warning("embedding_secret_unusable", extra={"collection": collection})
        return _degraded(identity, unusable)
    if not isinstance(secret, ApiKeySecret):
        logger.warning("embedding_secret_wrong_kind", extra={"collection": collection})
        return _degraded(identity, _WRONG_KIND[identity.key_source])
    return EmbeddingTarget(identity=identity, api_key=secret.api_key.get_secret_value())


_KEYED = frozenset({EmbeddingKeySource.ORGANIZATION, EmbeddingKeySource.CONNECTION})

# What a keyed source degrades to when its row is gone, and when it cannot be opened.
_KEY_FAILURES = {
    EmbeddingKeySource.ORGANIZATION: (
        EmbeddingKeySource.SECRET_MISSING,
        EmbeddingKeySource.SECRET_UNUSABLE,
    ),
    EmbeddingKeySource.CONNECTION: (
        EmbeddingKeySource.CONNECTION_KEY_MISSING,
        EmbeddingKeySource.CONNECTION_KEY_UNUSABLE,
    ),
}
_WRONG_KIND = {
    EmbeddingKeySource.ORGANIZATION: EmbeddingKeySource.SECRET_WRONG_KIND,
    EmbeddingKeySource.CONNECTION: EmbeddingKeySource.CONNECTION_KEY_UNUSABLE,
}


_CONNECTION_FAILURES = frozenset(
    {EmbeddingKeySource.CONNECTION_KEY_MISSING, EmbeddingKeySource.CONNECTION_KEY_UNUSABLE}
)


def _degraded(identity: TargetIdentity, source: EmbeddingKeySource) -> EmbeddingTarget:
    """The same target with no key, because its key could not be had.

    A connection's address goes too: it is the address of a keyed endpoint, and
    nothing may call that bare. A vendor's stays, as it always did - the client
    refuses on the empty key and names the collection.
    """
    base_url = "" if source in _CONNECTION_FAILURES else identity.base_url
    return EmbeddingTarget(
        identity=replace(identity, base_url=base_url, key_source=source), api_key=""
    )
