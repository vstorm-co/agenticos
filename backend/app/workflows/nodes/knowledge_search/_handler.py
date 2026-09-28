"""`knowledge.search`: find passages in knowledge collections, as typed sources.

The same retrieval an agent's knowledge tool runs - `RetrievalService`, scoped
per collection by the store's own resolution so a search never reaches another
tenant's rows - but handed back as `SourceRef`s a later node can bind to rather
than a citation string a model reads. No results is an answer, not a failure:
an empty `sources` flows on like any other.

Access is checked twice. Publishing refuses a collection the graph's author
cannot read (`check_resources`); a run re-checks every collection against the
run's own principal before searching, since a grant can be withdrawn between
the two, and refuses the whole search rather than quietly searching fewer
collections than the graph names.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.knowledge._search import get_retrieval_service
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_worker_db_context
from app.repositories import knowledge_base_repo
from app.services.collection_access import readable_kb
from app.services.rag.models import SearchResult
from app.services.workflow_execution import context
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


async def _readable(
    db: AsyncSession, auth: AuthContext, collection_ids: tuple[UUID, ...]
) -> tuple[list[str], list[int]]:
    """The vector collection names `auth` may read, and the indexes it may not."""
    found = await knowledge_base_repo.get_by_ids(db, collection_ids)
    names: list[str] = []
    refused: list[int] = []
    for index, collection_id in enumerate(collection_ids):
        kb = found.get(collection_id)
        if kb is None or not await readable_kb(db, auth, kb):
            refused.append(index)
        else:
            names.append(kb.collection_name)
    return names, refused


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a collection the graph's author cannot read."""
    if not isinstance(config, KnowledgeSearchConfig):
        return []
    _names, refused = await _readable(db, ctx, config.collection_ids)
    return [
        (f"collection_ids.{index}", "This collection does not exist or is not accessible")
        for index in refused
    ]


def _source(result: SearchResult, fallback_collection: str) -> SourceRef:
    metadata: dict[str, Any] = result.metadata
    page = metadata.get("page_num")
    chunk = metadata.get("chunk_num")
    document_id = metadata.get("document_id") or result.parent_doc_id
    return SourceRef(
        document_id=None if document_id is None else str(document_id),
        filename=str(metadata.get("filename", "unknown")),
        collection=str(metadata.get("collection") or fallback_collection),
        page=page if isinstance(page, int) else None,
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
    async with get_worker_db_context() as db:
        names, refused = await _readable(db, current.auth, config.collection_ids)
    if refused:
        return Failed(
            error=WorkflowError(
                code="COLLECTION_NOT_ACCESSIBLE",
                message="A collection this search names is gone or no longer accessible",
                details={"collection_ids": [str(config.collection_ids[i]) for i in refused]},
                # Access revoked since publishing: not a failure to route around.
                bypassable=False,
            )
        )
    service = get_retrieval_service()
    try:
        scopes = {
            name: await service.resolve_scope(name, current.organization_id) for name in names
        }
        if len(names) == 1:
            results = await service.retrieve(
                query=node_input.query,
                collection_name=names[0],
                scope=scopes[names[0]],
                limit=config.top_k,
            )
        else:
            results = await service.retrieve_multi(
                query=node_input.query, collection_names=names, scopes=scopes, limit=config.top_k
            )
    except AppException as exc:
        # Already an account of what is wrong - an embedding key not configured
        # names the setting - and its details are this codebase's own.
        return Failed(error=workflow_error(exc))
    except Exception:
        # A vector store or embedding client's own text can carry a request URL
        # with a key in it, so it stays in the log.
        logger.exception("workflow_knowledge_search_failed", extra={"collections": names})
        return Failed(
            error=WorkflowError(
                code="KNOWLEDGE_SEARCH_FAILED",
                message="The knowledge search failed",
                details={"collections": names},
                retryable=True,
            )
        )
    return Completed[KnowledgeSearchOutput](
        output=KnowledgeSearchOutput(sources=tuple(_source(r, names[0]) for r in results))
    )
