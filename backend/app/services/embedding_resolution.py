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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

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


@dataclass(frozen=True, repr=False)
class ResolvedEmbeddings:
    """Everything one collection's embedding call needs.

    `repr=False` on purpose: the dataclass carries a plaintext key, and the
    default repr is the way a key ends up in a log line.
    """

    model: str
    dim: int
    api_key: str

    def __repr__(self) -> str:
        return f"ResolvedEmbeddings(model={self.model!r}, dim={self.dim}, api_key='***')"


async def embeddings_for_collection(collection_name: str) -> ResolvedEmbeddings | None:
    """Resolve one collection's embedding model and credential.

    Returns None for a collection no knowledge base claims - the store then
    uses its deployment defaults, which is what such collections have always
    gotten. Opens its own session because the store embeds from places with no
    request in sight: a worker mid-ingestion, a capability mid-run.
    """
    async with get_db_context() as db:
        kb = await knowledge_base_repo.get_by_collection_name(db, collection_name)
        if kb is None:
            return None
        return ResolvedEmbeddings(
            model=kb.embedding_model,
            # The recorded width, not a fresh lookup: the table was created at
            # this number, and a later catalog change must not disagree with it.
            dim=kb.embedding_dim,
            api_key=await _api_key_for(db, kb),
        )


async def _api_key_for(db, kb: KnowledgeBase) -> str:
    """The organization's chosen key, or the deployment's.

    Every failure path lands on the deployment key with a log line rather than
    an exception: the choice of *whose key pays* must never decide *whether
    documents can be found*.
    """
    if kb.embedding_secret_id is None or kb.organization_id is None:
        return settings.OPENROUTER_API_KEY

    row = await organization_secret_repo.get(
        db, kb.embedding_secret_id, organization_id=kb.organization_id
    )
    if row is None:
        logger.warning("embedding_secret_missing", extra={"collection": kb.collection_name})
        return settings.OPENROUTER_API_KEY
    try:
        secret = unseal_secret(
            row.sealed_secret,
            kind=SecretKind(row.kind),
            scope=VaultScope.organization(kb.organization_id),
            key_version=row.key_version,
        )
    except Exception:
        logger.warning("embedding_secret_unusable", extra={"collection": kb.collection_name})
        return settings.OPENROUTER_API_KEY
    if not isinstance(secret, ApiKeySecret):
        logger.warning("embedding_secret_wrong_kind", extra={"collection": kb.collection_name})
        return settings.OPENROUTER_API_KEY
    return secret.api_key.get_secret_value()
