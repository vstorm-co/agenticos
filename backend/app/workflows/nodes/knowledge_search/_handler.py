"""`knowledge.search`: find passages in knowledge collections, as typed sources.

The same retrieval an agent's knowledge tool runs - `RetrievalService`, scoped
per collection by the knowledge base that was checked, so a search never reaches
another tenant's rows or an unselected same-named base - but handed back as
`SourceRef`s a later node can bind to rather
than a citation string a model reads. No results is an answer, not a failure:
an empty `sources` flows on like any other.

Access is checked twice. Publishing refuses a collection the graph's author
cannot read (`check_resources`); a run re-checks every collection against the
run's own principal before searching, since a grant can be withdrawn between
the two, and refuses the whole search rather than quietly searching fewer
collections than the graph names.
"""

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    SpendLedger,
    guarded_by,
    metered_by,
)
from app.agents.capabilities.knowledge._search import get_retrieval_service
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.db.vector_tables import VectorScope
from app.repositories import knowledge_base_repo
from app.services.collection_access import readable_kb
from app.services.rag.citation import cited_page
from app.services.rag.filters import RetrievalScope, bind_collection, can_union, scope_for
from app.services.rag.models import SearchResult
from app.services.spend import assert_organization_within_budget
from app.services.workflow_execution import budget, context
from app.services.workflow_execution.errors import workflow_error
from app.workflows.contracts.io import SourceRef
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError

logger = logging.getLogger(__name__)


class KnowledgeSearchConfig(BaseModel):
    """Which collections to search, and how many passages to return."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    collection_ids: tuple[UUID, ...] = Field(
        min_length=1,
        max_length=10,
        json_schema_extra={"x-resource": "collection"},
        description="The knowledge collections to search.",
    )
    top_k: int = Field(default=5, ge=1, le=50, description="The most passages to return.")


class KnowledgeSearchInput(BaseModel):
    """The question to search for, bound from an upstream output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1, max_length=4000)


class KnowledgeSearchOutput(BaseModel):
    """The passages found, best first. Empty when nothing matched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sources: tuple[SourceRef, ...] = ()


_SHARES_STORAGE = (
    "This collection shares its storage name with another one in this step that "
    "belongs to a different scope, so the two cannot be searched together. Search "
    "them in separate Knowledge search steps."
)


@dataclass
class _Collections:
    """What one search reads: each collection name once, under the union of its bases."""

    names: list[str] = field(default_factory=list)
    scopes: dict[str, VectorScope] = field(default_factory=dict)
    refused: list[int] = field(default_factory=list)
    """Indexes of the collections `auth` may not read."""
    clashing: list[int] = field(default_factory=list)
    """Indexes of collections whose name an earlier one holds under a scope they
    cannot be read with: an app-wide base and an organization's, say."""


async def _collections(
    db: AsyncSession, auth: AuthContext, collection_ids: tuple[UUID, ...]
) -> _Collections:
    """The collections `auth` may read, bound per name as one search reads them."""
    found = await knowledge_base_repo.get_by_ids(db, collection_ids)
    out = _Collections()
    for index, collection_id in enumerate(collection_ids):
        kb = found.get(collection_id)
        if kb is None or not await readable_kb(db, auth, kb):
            out.refused.append(index)
            continue
        bound = out.scopes.get(kb.collection_name)
        if bound is not None and not can_union(bound, kb.vector_scope):
            out.clashing.append(index)
            continue
        bind_collection(out.names, out.scopes, kb.collection_name, kb.vector_scope)
    return out


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a collection the graph's author cannot read, or cannot search with the rest."""
    if not isinstance(config, KnowledgeSearchConfig):
        return []
    found = await _collections(db, ctx, config.collection_ids)
    return [
        (f"collection_ids.{index}", "This collection does not exist or is not accessible")
        for index in found.refused
    ] + [(f"collection_ids.{index}", _SHARES_STORAGE) for index in found.clashing]


def _source(result: SearchResult, fallback_collection: str) -> SourceRef:
    metadata: dict[str, Any] = result.metadata
    chunk = metadata.get("chunk_num")
    document_id = metadata.get("document_id") or result.parent_doc_id
    return SourceRef(
        document_id=None if document_id is None else str(document_id),
        filename=str(metadata.get("filename", "unknown")),
        collection=str(metadata.get("collection") or fallback_collection),
        # Only a paged format's page: Markdown's stored "page 1" is the parser's,
        # and `agent.run` would cite it as a location (#2482).
        page=cited_page(metadata),
        chunk=chunk if isinstance(chunk, int) else None,
        score=result.score,
        content=result.content,
    )


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Search every configured collection the run's principal may still read."""
    if not isinstance(config, KnowledgeSearchConfig) or not isinstance(
        node_input, KnowledgeSearchInput
    ):
        return Failed(
            error=WorkflowError(
                code="SEARCH_NOT_CONFIGURED",
                message="A knowledge search needs collections and a bound query",
            )
        )
    current = context.current()
    try:
        async with get_worker_db_context() as db:
            found = await _collections(db, current.auth, config.collection_ids)
            await assert_organization_within_budget(db, current.organization_id)
            limits = await budget.provider_limits(
                db, organization_id=current.organization_id, remaining=current.budget_remaining
            )
    except BudgetExceeded:
        return Failed(
            error=WorkflowError(
                code="BUDGET_EXCEEDED",
                message="The organization's monthly budget is exhausted",
                bypassable=False,
            )
        )
    if found.refused:
        return Failed(
            error=WorkflowError(
                code="COLLECTION_NOT_ACCESSIBLE",
                message="A collection this search names is gone or no longer accessible",
                details={"collection_ids": [str(config.collection_ids[i]) for i in found.refused]},
                # Access revoked since publishing: not a failure to route around.
                bypassable=False,
            )
        )
    if found.clashing:
        return Failed(
            error=WorkflowError(
                code="COLLECTIONS_SHARE_STORAGE",
                message=_SHARES_STORAGE,
                details={"collection_ids": [str(config.collection_ids[i]) for i in found.clashing]},
                bypassable=False,
            )
        )
    names = found.names
    # Each name's checked bases, never the name resolved again: that could pick a
    # same-named base the run's principal cannot read.
    scopes: dict[str, RetrievalScope] = {
        name: scope_for(scope) for name, scope in found.scopes.items()
    }
    service = get_retrieval_service()
    ledger = SpendLedger()
    try:
        with metered_by(ledger), guarded_by(BudgetGuard(ledger=ledger, limits=limits)):
            if len(names) == 1:
                results = await service.retrieve(
                    query=node_input.query,
                    collection_name=names[0],
                    scope=scopes[names[0]],
                    limit=config.top_k,
                )
            else:
                results = await service.retrieve_multi(
                    query=node_input.query,
                    collection_names=names,
                    scopes=scopes,
                    limit=config.top_k,
                )
    except BudgetExceeded:
        return Failed(
            error=WorkflowError(
                code="BUDGET_EXCEEDED",
                message="The search reached a spending limit",
                bypassable=False,
            )
        )
    except AppException as exc:
        # Already an account of what is wrong - an embedding key not configured
        # names the setting - and its details are this codebase's own.
        return Failed(error=workflow_error(exc))
    except Exception as exc:
        # A vector store or embedding client's own text can carry a request URL
        # with a key in it, so it stays in the log.
        logger.warning(
            "workflow_knowledge_search_failed",
            extra={"collections": names, "error_type": type(exc).__name__},
        )
        return Failed(
            error=WorkflowError(
                code="KNOWLEDGE_SEARCH_FAILED",
                message="The knowledge search failed",
                details={"collections": names},
                retryable=True,
            )
        )
    finally:
        context.report_cost(ledger.total_usd, partial=ledger.has_unpriced_models)
    return Completed[KnowledgeSearchOutput](
        output=KnowledgeSearchOutput(sources=tuple(_source(r, names[0]) for r in results))
    )
