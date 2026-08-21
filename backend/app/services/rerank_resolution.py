"""Whether a collection reranks its search results - and whose key pays.

The sibling of :mod:`app.services.embedding_resolution`, and deliberately its
mirror image in shape. Retrieval asks per collection whether a reranker is
configured; the answer carries the reranker's model and the organization key it
runs on, or nothing.

Where embeddings *fall back* to the deployment key when a collection's chosen
one is gone, reranking *turns off*. There is no deployment reranker key - the
feature is off by default and on only when a collection names both a model and a
usable organization secret - so every path that is not "a usable key the
collection chose" resolves to `None` and retrieval behaves exactly as it did
before the feature. The distinction still has to be *said*, though: a collection
that chose a key and lost it is a misconfiguration an operator should see, where
a collection that chose nothing is the normal off state and must stay quiet. So
resolution classifies the reason with :class:`RerankKeySource` and logs the
three degraded ones, exactly as embedding resolution names its own.
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

logger = logging.getLogger(__name__)

# Secret purposes that can pay for reranking. Cohere is the only reranker today,
# and `cohere` is already a model-provider purpose - one Cohere API key reranks
# and chats alike - so this reuses it rather than minting a second entry that
# would collide with it. The tuple exists so a second provider is one entry.
RERANK_KEY_PURPOSES = ("cohere",)

# The rerank models this platform can actually run. Cohere Rerank 3.5 is the only
# one behind `CohereReranker` today; a value outside this set would be accepted,
# stored and displayed as configured, then fail every search inside Cohere - a
# request `_rank_and_truncate` swallows, so reranking would be silently off. So a
# model is validated at create and update against this tuple, which grows by one
# entry when a second model is supported.
SUPPORTED_RERANK_MODELS = ("rerank-v3.5",)


class RerankKeySource(StrEnum):
    """Why a collection did or did not get a reranker.

    Only :attr:`CONFIGURED` yields one. The rest all mean "no reranking", and
    they are kept apart for the same reason embedding resolution keeps its
    sources apart: telling "the collection chose no reranker" from "the key it
    chose is gone" is the difference between silence and a line an operator
    needs to see.
    """

    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    SECRET_MISSING = "secret_missing"
    SECRET_UNUSABLE = "secret_unusable"
    SECRET_WRONG_KIND = "secret_wrong_kind"

    @property
    def is_degraded(self) -> bool:
        """True when the collection asked for a reranker and did not get one.

        `NOT_CONFIGURED` is not degraded: a collection that named no reranker is
        supposed to have none, and warning on every unconfigured search would
        bury the three that mean a real misconfiguration.
        """
        return self in _DEGRADED


_DEGRADED = frozenset(
    {
        RerankKeySource.SECRET_MISSING,
        RerankKeySource.SECRET_UNUSABLE,
        RerankKeySource.SECRET_WRONG_KIND,
    }
)


@dataclass(frozen=True, repr=False)
class ResolvedReranker:
    """Everything one collection's rerank call needs.

    `repr=False` for the same reason :class:`ResolvedEmbeddings` carries it: the
    dataclass holds a plaintext key, and the default repr is how a key reaches a
    log line.
    """

    model: str
    api_key: str

    def __repr__(self) -> str:
        return f"ResolvedReranker(model={self.model!r}, api_key='***')"


async def reranker_for_collection(
    collection_name: str, organization_id: UUID | None
) -> ResolvedReranker | None:
    """Resolve one collection's reranker, or `None` if it has none.

    `None` for a collection no knowledge base claims, for one that named no
    reranker, and for one whose chosen key is missing, unusable or the wrong
    kind - the last three with a warning, because they are a misconfiguration
    rather than the off state. Opens its own session because retrieval reaches
    here from places with no request in sight: an agent mid-run, a direct search.

    `organization_id` scopes the resolution: `collection_name` is not unique
    across tenants, so resolving by name alone could read another organization's
    rerank config and unseal its key (#913). The caller passes the organization
    the search is acting for.
    """
    async with get_db_context() as db:
        kb = await knowledge_base_repo.get_for_collection(db, collection_name, organization_id)
        if kb is None:
            return None
        resolved, source = await _resolve_reranker(db, kb)
        if source.is_degraded:
            logger.warning("rerank_%s", source.value, extra={"collection": collection_name})
        return resolved


async def _resolve_reranker(
    db: AsyncSession, kb: KnowledgeBase
) -> tuple[ResolvedReranker | None, RerankKeySource]:
    """The reranker a collection is configured for, or `None` and why not.

    Unlike embedding resolution, no failure lands on a deployment key: there is
    none, so every path but a usable organization secret returns `None`. The
    second element is what stops that from being invisible - it is carried out to
    the log line above.
    """
    model = kb.rerank_model
    secret_id = kb.rerank_secret_id
    organization_id = kb.organization_id
    if model is None and secret_id is None:
        return None, RerankKeySource.NOT_CONFIGURED
    if model is None or secret_id is None or organization_id is None:
        # A half-configured reranker, not the off state. The pair is written
        # together - create and update enforce it - but deleting the chosen
        # secret nulls rerank_secret_id through the foreign key while leaving
        # rerank_model set, and that stopped reranking with no signal at all
        # until this told the half state apart from the null/null off state.
        return None, RerankKeySource.SECRET_MISSING

    row = await organization_secret_repo.get(db, secret_id, organization_id=organization_id)
    if row is None:
        return None, RerankKeySource.SECRET_MISSING
    try:
        secret = unseal_secret(
            row.sealed_secret,
            kind=SecretKind(row.kind),
            scope=VaultScope.organization(organization_id),
            key_version=row.key_version,
        )
    except Exception:
        return None, RerankKeySource.SECRET_UNUSABLE
    if not isinstance(secret, ApiKeySecret):
        return None, RerankKeySource.SECRET_WRONG_KIND
    resolved = ResolvedReranker(model=model, api_key=secret.api_key.get_secret_value())
    return resolved, RerankKeySource.CONFIGURED
